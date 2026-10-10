## What and why

<!-- One paragraph: the problem, the change, and why this approach. Link the issue. -->

## How it was verified

- [ ] `make lint test typecheck` passes
- [ ] Detection change? A suspicious scenario **and** its legitimate twin are covered
- [ ] UI change? Screenshot or short clip attached
- [ ] Infra change? `terraform plan` / `helm template` output reviewed

## Risk

<!-- What could break, who is affected, how to roll back (revert the release PR / Argo Rollouts abort). -->

- [ ] New architectural choice recorded as an ADR in `docs/adr/`
- [ ] No real customer, staff or transaction data in this PR
