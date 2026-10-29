# CatchMeIfYouCan Python integration scaffold

`api_client.py` re-exports the dependency-free shared client in `client.py`.
The client covers the backend routes verified in
the current Spring Boot codebase. It uses `CATCHMEIFYOUCAN_BASE_URL` when set,
otherwise `http://localhost:8080`.

```python
from api_client import CatchMeIfYouCanApiClient

api = CatchMeIfYouCanApiClient()
scenario = api.create_scenario(
    source_company_id=1,
    target_company_id=2,
    amount="10000000.00",
)
state = api.get_scenario(scenario["id"])

action = api.create_fraudster_action(
    scenario_id=state["id"],
    action_type="DIRECT_TRANSFER",
    source_position_id=state["positions"][0]["id"],
)
api.execute_fraudster_action(action["id"])
api.submit_investigator_action(
    scenario_id=state["id"],
    action_type="OBSERVE_COMPANY",
    company_id=2,
)
```

Run from this directory with:

```powershell
$env:CATCHMEIFYOUCAN_BASE_URL = "http://localhost:8080"
python -c "from api_client import CatchMeIfYouCanApiClient; print(CatchMeIfYouCanApiClient().get_scenario(1))"
```

The client does not add reset, company-list, or action-list methods because
those routes are not part of the verified scenario/action API surface. It can
read transaction history from the existing scenario transaction endpoint.
Scenario creation starts a new independent episode; no reset route is exposed.

A scenario stays active across repeated fraudster turns. Each fraudster turn is
followed by up to three investigator actions. A correct company flag ends the
scenario; an incorrect flag consumes one investigator action and play
continues. The backend defaults to at most 10 fraudster turns, configurable
with `simulation.fraud.max-turns`. Reaching that bound without a correct flag
ends with status `MAX_TURNS_REACHED`, which is a distinct terminal outcome from
achieving the financial objective (`financialObjectiveAchieved`).

RL training assigns separate terminal rewards: +5 for achieving the financial
objective, +5 for evading detection through the turn limit, and -10 for a
correct detection. Therefore detection is penalized even when the money reached
its destination. Evaluator labels are loaded only after a completed scenario
and do not enter live policy observations.

The placeholder coordinator can run a conservative episode using only exposed
state:

```powershell
python run_episode.py --scenario-id 1
```

Or create a new episode:

```powershell
python run_episode.py --source-company-id 1 --target-company-id 2 --amount 10000000.00
```

Run independent evaluation episodes sequentially and print a JSON report:

```powershell
python evaluate.py --scenarios 10 --source-company-id 1 --target-company-id 2 --amount 10000000.00 --max-actions 20 --continue-on-failure
```

The evaluation harness creates a fresh scenario for each episode and keeps
scenario IDs separate. It reports terminal outcomes, infrastructure failures,
action-limit episodes, financial-objective outcomes, and sanitized investigator
evidence. The financial-objective rate is a simulation outcome, not
fraud-detection accuracy. It does not call company-list endpoints or expose
hidden company labels to either policy.

The placeholder fraudster selects only `DIRECT_TRANSFER`. ROUTE_TRANSFER and
SPLIT_TRANSFER need eligible intermediate-company IDs, which are not included
in scenario state. The placeholder investigator uses `OBSERVE_COMPANY`; it
does not select `TRACE_TRANSACTION` because transaction IDs are not exposed by
the scenario-state response.

Offline detection metrics are opt-in and are reported as **source/target
baseline metrics**. Each record is one scenario-company pair for the source or
target company declared by that scenario; it is not a count of unique
companies or individual flag actions. Labels and persisted `FLAG_COMPANY`
decisions are read only after every episode has a valid terminal outcome and
are never sent through the agent client or policy state.

The evaluator does not yet report a discovered-company metric. Investigator
action rows persist the company investigated or the transaction traced, but do
not persist the director-investigation response that listed associated
companies. Reconstructing that list from the current director graph could
include companies that were not actually exposed when the action occurred, so
it is not a reliable historical candidate population. A future broader metric
needs a persisted snapshot of the evidence actually returned to the
investigator.

Configure a separately provisioned read-only PostgreSQL evaluator role through
an environment variable; do not reuse or print application credentials:

```powershell
$env:CATCHMEIFYOUCAN_EVALUATOR_DATABASE_URL = "postgresql://<read-only-evaluator-user>:<password>@localhost:5432/catchmeifyoucan"
python evaluate.py --scenarios 10 --source-company-id 1 --target-company-id 2 --amount 10000000.00 --detection-metrics
```

The option fails explicitly when the evaluator URL, PostgreSQL driver, labels,
or completed evaluation data is missing. It does not turn unavailable data into
zero-valued metrics.
