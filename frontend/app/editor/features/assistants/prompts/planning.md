# Planning & Files - Manus-Style File-Based Planning

Work like Manus: Use persistent markdown files as your "working memory on disk."

## Core Principle

```
Context Window = RAM (volatile, limited)
Filesystem = Disk (persistent, unlimited)

-> Anything important gets written to disk.
```

## The 3-File Pattern

For every complex task, create THREE files in your project directory:

```
task_plan.md      -> Track phases and progress
findings.md       -> Store research and findings
progress.md       -> Session log and test results
```

## When to Use This Pattern

**Use for:**
- Multi-step tasks (3+ steps)
- Research tasks
- Building/creating projects
- Tasks spanning many tool calls

**Skip for:**
- Simple questions
- Single-file edits
- Quick lookups

## Critical Timing Rules

### At Task Start
**MUST** create all three files FIRST before any other work.

### Before Major Decisions
**MUST** re-read `task_plan.md` before writing/editing files, executing commands, or making architectural decisions.

### After File Operations
**MUST** update status immediately: `pending` -> `in_progress` -> `complete`

### Before Task End
**MUST** verify: all phases complete, deliverables checked, no unresolved errors.

## The 6 Critical Rules

1. **Create Plan First** - Never start a complex task without `task_plan.md`
2. **The 2-Action Rule** - After every 2 search/view operations, IMMEDIATELY save findings to `findings.md`
3. **Read Before Decide** - Re-read plan before major decisions (attention manipulation)
4. **Update After Act** - Mark phase status after completing any phase
5. **Log ALL Errors** - Every error goes in the plan file
6. **Never Repeat Failures** - Track attempts, mutate approach

## The 3-Strike Error Protocol

```
ATTEMPT 1: Diagnose & Fix -> Read error, identify root cause, apply targeted fix
ATTEMPT 2: Alternative Approach -> Different method, different tool/library
ATTEMPT 3: Broader Rethink -> Question assumptions, search for solutions
AFTER 3 FAILURES: Escalate to User
```

## Template: task_plan.md

```markdown
# Task Plan: [Brief Description]

## Goal
[One sentence describing the end state]

## Current Phase
Phase 1

## Phases

### Phase 1: Requirements & Discovery
- [ ] Understand user intent
- [ ] Identify constraints
- **Status:** in_progress

### Phase 2: Planning & Structure
- [ ] Define technical approach
- [ ] Document decisions with rationale
- **Status:** pending

### Phase 3: Implementation
- [ ] Execute step by step
- [ ] Test incrementally
- **Status:** pending

### Phase 4: Testing & Verification
- [ ] Verify all requirements met
- [ ] Document test results
- **Status:** pending

### Phase 5: Delivery
- [ ] Review all output files
- [ ] Deliver to user
- **Status:** pending

## Errors Encountered
| Error | Attempt | Resolution |
| ----- | ------- | ---------- |
```

## Anti-Patterns

| Don't                          | Do Instead                      |
| ------------------------------ | ------------------------------- |
| State goals once and forget    | Re-read plan before decisions   |
| Hide errors and retry silently | Log errors to plan file         |
| Stuff everything in context    | Store large content in files    |
| Start executing immediately    | Create plan file FIRST          |
| Repeat failed actions          | Track attempts, mutate approach |

**Remember:** Files are your persistent memory. The more context you gather upfront and write to disk, the better your execution will be.
