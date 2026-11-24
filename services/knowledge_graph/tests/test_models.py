from datetime import UTC, datetime
from uuid import UUID

import pytest
from mage_med_contracts import AssertionType, VerificationStatus
from mage_med_knowledge_graph import (
    GraphNode,
    GraphRelation,
    GraphTier,
    NodeKind,
    RelationKind,
)
from pydantic import ValidationError

PATIENT_ID = UUID("10000000-0000-4000-8000-000000000001")
SOURCE_ID = UUID("10000000-0000-4000-8000-000000000002")
PROVENANCE_ID = UUID("10000000-0000-4000-8000-000000000003")
NOW = datetime(2026, 11, 24, 0, 0, tzinfo=UTC)


def _node(kind: NodeKind, **changes: object) -> GraphNode:
    values: dict[str, object] = {
        "id": PATIENT_ID if kind is NodeKind.PATIENT else UUID(int=list(NodeKind).index(kind) + 10),
        "kind": kind,
        "patient_id": PATIENT_ID
        if kind
        in {
            NodeKind.PATIENT,
            NodeKind.ENCOUNTER,
            NodeKind.CONDITION,
            NodeKind.OBSERVATION,
            NodeKind.MEDICATION,
            NodeKind.CLINICAL_NOTE,
            NodeKind.HYPOTHESIS,
            NodeKind.INFERENCE_RUN,
        }
        else None,
        "source_artifact_id": SOURCE_ID,
        "provenance_id": PROVENANCE_ID,
        "imported_at": NOW,
        "assertion_type": (
            AssertionType.HYPOTHESIZED
            if kind in {NodeKind.HYPOTHESIS, NodeKind.INFERENCE_RUN}
            else AssertionType.OBSERVED
        ),
    }
    values.update(changes)
    return GraphNode.model_validate(values)


def test_all_core_nodes_have_exactly_one_logical_tier_and_provenance() -> None:
    expected = {
        NodeKind.PATIENT: GraphTier.TEMPORAL_PATIENT,
        NodeKind.ENCOUNTER: GraphTier.TEMPORAL_PATIENT,
        NodeKind.CONDITION: GraphTier.TEMPORAL_PATIENT,
        NodeKind.OBSERVATION: GraphTier.TEMPORAL_PATIENT,
        NodeKind.MEDICATION: GraphTier.TEMPORAL_PATIENT,
        NodeKind.CLINICAL_NOTE: GraphTier.TEMPORAL_PATIENT,
        NodeKind.CLINICAL_CONCEPT: GraphTier.BIOMEDICAL,
        NodeKind.EVIDENCE_DOCUMENT: GraphTier.EVIDENCE_PROVENANCE,
        NodeKind.EVIDENCE_CHUNK: GraphTier.EVIDENCE_PROVENANCE,
        NodeKind.SOURCE_ARTIFACT: GraphTier.EVIDENCE_PROVENANCE,
        NodeKind.HYPOTHESIS: GraphTier.NONCONFIRMED_INFERENCE,
        NodeKind.INFERENCE_RUN: GraphTier.NONCONFIRMED_INFERENCE,
    }
    assert {_node(kind).tier for kind in NodeKind} == set(GraphTier)
    assert all(_node(kind).tier is tier for kind, tier in expected.items())
    assert all(_node(kind).provenance_id == PROVENANCE_ID for kind in NodeKind)


def test_patient_scope_time_and_reserved_property_invariants() -> None:
    with pytest.raises(ValidationError, match="requires explicit patient scope"):
        _node(NodeKind.OBSERVATION, patient_id=None)
    with pytest.raises(ValidationError, match="cannot carry patient scope"):
        _node(NodeKind.CLINICAL_CONCEPT, patient_id=PATIENT_ID)
    with pytest.raises(ValidationError, match="must include a UTC offset"):
        _node(NodeKind.CONDITION, imported_at=datetime(2026, 1, 1))
    with pytest.raises(ValidationError, match="reserved graph properties"):
        _node(NodeKind.OBSERVATION, properties={"patient_id": "override"})


def test_hypotheses_and_automatic_concepts_cannot_become_confirmed_facts() -> None:
    with pytest.raises(ValidationError, match="must remain unverified/nonconfirmed"):
        _node(NodeKind.HYPOTHESIS, verification_status=VerificationStatus.VERIFIED)
    with pytest.raises(ValidationError, match="model_inferred or hypothesized"):
        _node(NodeKind.HYPOTHESIS, assertion_type=AssertionType.CLINICIAN_CONFIRMED)
    with pytest.raises(ValidationError, match="automatically extracted concepts"):
        _node(
            NodeKind.CLINICAL_CONCEPT,
            assertion_type=AssertionType.EXTRACTED,
            verification_status=VerificationStatus.VERIFIED,
        )


def test_relationship_endpoint_scope_and_noncausal_invariants() -> None:
    base = {
        "id": UUID("20000000-0000-4000-8000-000000000001"),
        "source_id": PATIENT_ID,
        "source_kind": NodeKind.PATIENT,
        "target_id": UUID("20000000-0000-4000-8000-000000000002"),
        "target_kind": NodeKind.OBSERVATION,
        "patient_id": PATIENT_ID,
        "source_artifact_id": SOURCE_ID,
        "provenance_id": PROVENANCE_ID,
        "created_at": NOW,
        "assertion_type": AssertionType.OBSERVED,
    }
    relation = GraphRelation(kind=RelationKind.HAS_OBSERVATION, **base)
    assert relation.patient_id == PATIENT_ID
    with pytest.raises(ValidationError, match="does not allow"):
        GraphRelation(kind=RelationKind.HAS_NOTE, **base)
    with pytest.raises(ValidationError, match="require explicit patient scope"):
        GraphRelation(kind=RelationKind.HAS_OBSERVATION, **{**base, "patient_id": None})

    concept_relation = {
        **base,
        "kind": RelationKind.ASSOCIATED_WITH,
        "source_kind": NodeKind.CLINICAL_CONCEPT,
        "target_kind": NodeKind.CLINICAL_CONCEPT,
        "patient_id": None,
    }
    with pytest.raises(ValidationError, match="reserved graph properties"):
        GraphRelation(**concept_relation, properties={"causal": True})


def test_hypothesis_evidence_edges_remain_unverified() -> None:
    values = {
        "id": UUID("30000000-0000-4000-8000-000000000001"),
        "kind": RelationKind.SUPPORTED_BY,
        "source_id": UUID("30000000-0000-4000-8000-000000000002"),
        "source_kind": NodeKind.HYPOTHESIS,
        "target_id": UUID("30000000-0000-4000-8000-000000000003"),
        "target_kind": NodeKind.EVIDENCE_CHUNK,
        "patient_id": PATIENT_ID,
        "source_artifact_id": SOURCE_ID,
        "provenance_id": PROVENANCE_ID,
        "created_at": NOW,
        "assertion_type": AssertionType.HYPOTHESIZED,
    }
    assert GraphRelation(**values).verification_status is VerificationStatus.UNVERIFIED
    with pytest.raises(ValidationError, match="must remain unverified"):
        GraphRelation(**values, verification_status=VerificationStatus.VERIFIED)
