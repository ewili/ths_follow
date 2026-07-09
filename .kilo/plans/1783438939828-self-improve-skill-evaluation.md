# Evaluation: `self-improve` skill

## Goal
Assess the quality of the `self-improve` skill (and its references/scripts) and produce prioritized, implementation-ready improvements. This is a review, not a code-change request.

## Scorecard
| Dimension | Rating | Notes |
|-----------|--------|-------|
| Structure / progressive disclosure | Strong | Main SKILL.md (353 lines) + 9 focused references + 3 scripts |
| Core principle clarity | Strong | "Extend, don't bloat" repeated and enforced via red flags |
| Classification heuristics | Good, but internally contradictory | Quantified thresholds conflict with worked examples |
| Cross-IDE portability | Partial | Scripts Claude/Qoder-only; other IDEs "skip" |
| Verification / safety | Strong | Read-back, replace_all+grep persist check, no auto-commit |
| Self-consistency of own rules | Weak | Violates its own "steps>=3 -> skill" rule in its own examples |
| Success criteria | Missing | No pass/fail definition for a self-improve run |
| External dependencies | Undeclared | Assumes skill-creator / using-superpowers / writing-patterns |

## Strengths (keep)
- Phase 0 mandatory read-only audit before any write.
- Phase 2.5 cross-lesson consolidation prevents skill fragmentation.
- Red flags table (24 rows) catches common agent mistakes.
- Trigger Audit Mode reasoning (description is the only pre-trigger signal).
- replace_all+grep persistence check addresses real Windows UTF-8 BOM bug.

## Concrete issues (with locations)
1. Contradiction: "steps >= 3 -> skill" vs examples say "3 steps -> rule".
   - SKILL.md:47 decision flow: `步骤 >= 3 ... -> 技能`.
   - references/decision-examples.md:18-26 (Case 2): 3-step pre-commit flow -> rule ("step count is not the deciding factor").
   - Most damaging inconsistency; agents will over-create skills. Case 2's reasoning (always-applies vs on-demand) is correct; the flow's hard branch is wrong.
2. Inconsistent line threshold 50 vs 60.
   - SKILL.md:47,69 rule<60 skill>60; decision-examples.md:154 "<60" but Case1 says "~50"; storage-architecture.md:11 "~50 lines".
   - Unify on 60.
3. Rule-vs-memory boundary fuzzy; no worked examples (unlike rule-vs-skill's 13 cases).
4. No success/validation criteria for core flow (only Evolution Mode has validation).
5. Undeclared external dependencies (skill-creator, using-superpowers, writing-patterns) -> silent degradation.
6. No cross-run dedup guarantee; Phase 0 grep is discipline-dependent.
7. skill-first heuristic + contradictory steps>=3 compounds over-skilling.

## Prioritized improvements (implementation tasks)
1. Fix decision-flow contradiction (#1): in SKILL.md:44-59 replace hard `步骤 >= 3 -> 技能` with "multi-step AND on-demand/branchy -> skill; short always-applies constraint -> rule even if 3 steps"; add note reconciling with Case 2.
2. Unify line threshold to 60 (#2) across decision-examples.md and storage-architecture.md.
3. Add 2-3 rule-vs-memory examples to decision-examples.md.
4. Add acceptance checklist to Phase 6 (#4): every create/extend row traceable to written file; AGENTS.md gotcha for every new skill; memory INDEX.md updated; no duplicate file.
5. Add "Dependencies / graceful fallback" section listing skill-creator/using-superpowers/writing-patterns and fallback behavior.
6. Add slug-collision check in audit-agents-structure.ps1 (#6).

## Validation
- After fixes, re-read SKILL.md decision flow + decision-examples.md and confirm no rule-vs-skill threshold conflict and a single canonical line number (60).
- Confirm every reference link in SKILL.md resolves to an existing file.
