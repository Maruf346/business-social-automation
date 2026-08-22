# Codex Project Notes

This folder is the living handover and development context for the TattooHysteria Ink-Flow backend.

When code changes, update the relevant files here in the same development pass. These notes should stay aligned with the repository, not become a one-time handover snapshot.

## Files

- `PROJECT_CONTEXT.md` - what the project is, what this backend owns, and how the main flows work.
- `AI_INTEGRATION_CONTRACT.md` - AI endpoint payloads, responses, and backend persistence rules.
- `HANDOVER_AUDIT.md` - Milestone 1 promises compared with evidence in the current codebase.
- `MILESTONE_2_PLAN.md` - implementation plan for the remaining workflow and production work.
- `TECH_DEBT_AND_RISKS.md` - known code, architecture, deployment, and product risks.
- `DEVELOPMENT_GUIDE.md` - local setup, commands, endpoints, and integration notes.

## Documentation Rule

For every meaningful backend change:

1. Update code.
2. Run the relevant checks/tests.
3. Update the matching `.codex/*.md` context file, especially `AI_INTEGRATION_CONTRACT.md` when AI payloads or persistence rules change.
4. Mention both code and documentation changes in the final summary.
