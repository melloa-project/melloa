GRANT USAGE ON SCHEMA melloa TO melloa_change_planner, melloa_change_applier;

GRANT SELECT ON melloa.self_changes
    TO melloa_change_planner, melloa_change_applier;

GRANT UPDATE (
    state,
    base_revision,
    proposal_summary,
    proposal_patch,
    proposal_digest,
    failure_reason,
    attempt_count,
    available_at,
    lease_owner,
    lease_expires_at,
    updated_at
) ON melloa.self_changes TO melloa_change_planner;

GRANT UPDATE (
    state,
    candidate_revision,
    failure_reason,
    attempt_count,
    available_at,
    lease_owner,
    lease_expires_at,
    updated_at,
    deployed_at
) ON melloa.self_changes TO melloa_change_applier;

GRANT INSERT ON melloa.self_change_events
    TO melloa_change_planner, melloa_change_applier;

GRANT USAGE, SELECT ON SEQUENCE melloa.self_change_events_event_sequence_seq
    TO melloa_change_planner, melloa_change_applier;
