# CatchMeIfYouCan
### Intelligent Financial Fraud Investigation Using Graph Analysis, Fuzzy Logic, and Reinforcement Learning

CatchMeIfYouCan is an academic project that simulates financial fraud through a network of companies and transactions. It allows a fraudster agent to move money through company accounts while an investigator agent examines available evidence and attempts to identify suspicious companies.

The project combines a web-based simulation, a Spring Boot backend, a PostgreSQL database, Python-based reinforcement learning agents, and a risk analyzer that uses company information and transaction-network evidence.

The objective is to explore how graph algorithms, heuristic reasoning, fuzzy logic, and reinforcement learning can support fraud investigation in a controlled and explainable environment.

> **Project status:** Working academic simulation and experimental AI prototype. The application and investigation workflows are implemented, but the reinforcement learning agents have important training and generalization limitations. This project is not a production fraud-detection system.

---

## Table of Contents

- [Overview](#overview)
- [Problem Statement](#problem-statement)
- [Objectives](#objectives)
- [Key Features](#key-features)
- [Technology Stack](#technology-stack)
- [System Architecture](#system-architecture)
- [How the Simulation Works](#how-the-simulation-works)
- [Fraud Risk Analyzer](#fraud-risk-analyzer)
- [Graph Analysis and AI Techniques](#graph-analysis-and-ai-techniques)
- [Reinforcement Learning Implementation](#reinforcement-learning-implementation)
- [Reward Functions and Evaluation](#reward-functions-and-evaluation)
- [Database and Data Model](#database-and-data-model)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
- [Configuration](#configuration)
- [Running the Application](#running-the-application)
- [Testing](#testing)
- [Current Limitations and Weaknesses](#current-limitations-and-weaknesses)
- [Security and Privacy Considerations](#security-and-privacy-considerations)
- [Future Improvements](#future-improvements)
- [Academic Scope](#academic-scope)
- [Contributing](#contributing)
- [License](#license)

---

## Overview

Financial fraud can involve multiple companies, shared directors, suspicious business relationships, and a sequence of transactions intended to obscure the movement of money.

Examining an isolated transaction may not reveal the complete picture. Relationships between companies and the sequence of transactions can provide additional context.

CatchMeIfYouCan models this problem as an interactive environment containing:

- Companies with business profiles and financial information.
- Directors and relationships between companies.
- Transactions connecting companies in a financial network.
- A fraudster that chooses actions to move money.
- An investigator that examines evidence and chooses companies to flag.
- A risk analyzer that combines available company and network information into an interpretable risk score.
- Reinforcement learning agents that learn action preferences from rewards received during simulated episodes.

The application allows users to explore the investigation process, observe agent actions, inspect company information, and examine the evidence used to assess potential fraud.

The environment is synthetic. Its purpose is to demonstrate AI techniques and their limitations, rather than to make real-world allegations or financial decisions.

## Problem Statement

Traditional rule-based fraud detection can struggle with situations in which suspicious activity is distributed across multiple transactions or related companies.

The project investigates the following question:

**Can graph-based evidence, fuzzy risk assessment, and reinforcement learning be combined in a simulation to study financial fraud and investigation strategies?**

The project approaches this question through two related tasks:

1. **Fraud simulation:** Move funds through a company network while making sequential decisions under the constraints of the simulation.
2. **Fraud investigation:** Examine public company information, transaction evidence, and relationships to decide which companies warrant investigation or a fraud flag.

The investigator must make decisions using the information available at the time. Ground-truth labels are used for training and evaluation where appropriate, but are not intended to be exposed as live investigator observations.

## Objectives

- Model financial transactions as a network of connected companies.
- Generate synthetic legitimate companies, shell-company candidates, directors, and transactions.
- Simulate a fraudster's financial actions.
- Implement an investigator workflow with actions such as observing evidence, investigating companies, and flagging candidates.
- Use graph relationships and transaction patterns to identify potentially suspicious behavior.
- Apply fuzzy logic to represent uncertainty in risk assessment.
- Experiment with reinforcement learning for sequential decision-making.
- Measure detection behavior using metrics such as precision, recall, F1-score, and the confusion matrix.
- Present the simulation through an interactive web interface.
- Separate observed evidence from evaluation labels to reduce information leakage.

## Key Features

### 1. Company and director network

The application models companies, directors, company-director associations, and financial transactions. Relationships can provide investigative context beyond an individual transaction.

### 2. Synthetic financial environment

The simulation generates legitimate companies and shell-company examples, along with background transactions. The generated data includes patterns such as company age, employee counts, director reuse, and address reuse.

These patterns create a controlled environment for experimenting with risk assessment. They should not be interpreted as universal indicators of real-world fraud.

### 3. Interactive fraud simulation

A scenario begins with a funded financial position. The fraudster can select legal actions to move funds, subject to the simulation's state and action constraints.

Supported fraudster action types include:

- `DIRECT_TRANSFER`
- `ROUTE_TRANSFER`
- `SPLIT_TRANSFER`
- `WAIT`

The backend validates actions and maintains scenario state, financial positions, and transaction history.

### 4. Investigator workflow

The investigator receives a limited number of actions after a fraudster move. Depending on the current state and legal actions, the investigator can inspect evidence, investigate companies, or flag a company.

A correct flag can terminate a scenario. An incorrect flag consumes investigative resources. If the turn limit is reached without successful detection, the scenario terminates according to the simulation's lifecycle rules.

### 5. Interactive frontend

The web interface provides scenario controls, company information, transaction-network visualization, agent actions, and investigation feedback.

The agent demonstration supports observing fraudster moves followed by investigator actions. The interface also supports a human-controlled fraudster mode against the learned investigator.

### 6. Explainable risk output

The risk analyzer presents a numerical risk score, a qualitative category, and contributing evidence such as company age, shared resources, and transaction context.

It also distinguishes unavailable information from observed risk evidence.

### 7. Python RL experimentation

The separate `rl-agents/` module contains the Python client, state abstraction, Q-learning implementation, agent policies, training and evaluation runners, heuristic baseline, and tests.

The module is designed to make agent behavior and evaluation results inspectable rather than treating the learned policy as an unexplained prediction.

---

## Technology Stack

| Component | Technology |
|---|---|
| Backend | Java, Spring Boot |
| Database | PostgreSQL |
| Persistence | Spring Data JPA / Hibernate |
| Build system | Maven and Maven Wrapper |
| Frontend | HTML, CSS, JavaScript |
| RL implementation | Python |
| Learning approach | Tabular Q-learning |
| Risk assessment | Fuzzy logic and rule-based evidence aggregation |
| Network analysis | Company relationships and transaction graph traversal |
| Testing | JUnit, Spring Boot tests, Python unit tests, JavaScript tests |
| Version control | Git and GitHub |

The project combines a Java web application with a separate Python agent implementation. The exact Python interpreter and Java version should be compatible with the project scripts and Maven configuration.

## System Architecture

```text
                         User / Browser
                               |
                               v
                     HTML + CSS + JavaScript
                               |
                         HTTP / REST API
                               |
                               v
                    Spring Boot Application
                               |
               +---------------+---------------+
               |               |               |
               v               v               v
         Company and      Fraud Scenario    Investigation
         Director Data      Management         Services
               |               |               |
               +---------------+---------------+
                               |
                               v
                           PostgreSQL
                               ^
                               |
                      Python Agent Client
                               |
                  +------------+------------+
                  |            |            |
                  v            v            v
             Q-learning    Agent State    Training and
               Policies    Abstraction    Evaluation
                  |
                  v
          Fraudster / Investigator
```

The Java application manages the simulation lifecycle, validates actions, and persists domain data. The Python module implements the learning and evaluation logic and communicates with the application through its client/API integration.

The frontend is served as static resources by the Spring Boot application. The exact set of available endpoints and request formats can be inspected in the controller and DTO classes under `src/main/java/catchmeifyoucan/`.

## How the Simulation Works

### Step 1: Initialize the environment

The application provides a synthetic network of companies, directors, and transactions. Shell-company examples are generated using predefined characteristics.

The initial financial position provides funds that can be transferred during a scenario.

### Step 2: Start a scenario

A scenario records its current status, turn, acting role, financial positions, and action history.

A newly created scenario starts with the fraudster's turn.

### Step 3: Fraudster selects an action

The fraudster selects one of the legal actions available in the current state. A transfer can move money directly, route it through an intermediary, or split it across destinations. The agent can also wait.

The backend checks the action against the current scenario and available positions before applying it.

### Step 4: Investigator examines evidence

After the fraudster acts, the investigator receives a bounded action budget. The investigator can examine the available evidence and decide whether to flag a candidate company.

The investigator's decision should be based on the permitted observation, not on the hidden ground-truth label.

### Step 5: Update the scenario

The system records actions and updates positions and transaction history. The scenario continues until a terminal condition is reached, such as a successful flag or the maximum-turn limit.

### Step 6: Evaluate the outcome

The scenario outcome and relevant labels can be used to assess the investigator's behavior. Training and evaluation code calculate detection metrics from the eligible candidate population.

**Important distinction:** Successfully moving money, detecting a shell-company candidate, and identifying a company that actually participated in a fraudulent path are different objectives. They must be evaluated separately.

---

## Fraud Risk Analyzer

The risk analyzer is a separate component from the reinforcement learning agents.

It combines available company attributes and network evidence to produce an interpretable risk assessment.

### Evidence used

Depending on data availability, the analyzer considers evidence such as:

- Company age.
- Employee count and company profile.
- Shared directors.
- Shared addresses or other resources.
- Transaction volume and amount context.
- Relationships and transaction records reachable through the company network.

The analyzer can also display data completeness and explanatory observations so that a user can understand why a score was produced.

### Fuzzy logic

Fuzzy logic represents the degree to which an observation belongs to a linguistic category, rather than forcing every measurement into a binary true-or-false classification.

For example, a company's age may have different degrees of membership in categories such as relatively young or established. These membership values can be combined with other evidence according to the analyzer's rules.

The resulting score is mapped to a numerical risk output and a qualitative category.

A missing or unavailable-data case can produce a neutral score, such as 50/100 with a Medium label, according to the configured fallback behavior. This is a presentation fallback, not proof that the company has medium fraud risk.

### Graph traversal and transaction context

Graph traversal can help discover relationships between companies and trace transaction paths. Breadth-first search (BFS) is useful for exploring a network level by level, while depth-first search (DFS) is useful for exploring a branch of connected nodes.

The risk analyzer can use transaction and relationship context to support its assessment. However, finding a connected company does not establish that the company participated in fraud. Shared directors, addresses, and transaction connections can also occur in legitimate businesses.

The score is a heuristic risk indicator, not a calibrated probability of fraud.

---

## Graph Analysis and AI Techniques

The project provides a foundation for demonstrating several AI and algorithmic concepts.

| Technique | Role in the project | Important qualification |
|---|---|---|
| BFS | Explore connected companies or transaction networks by distance | Reachability does not establish guilt |
| DFS | Explore connected paths and relationship branches | Results depend on traversal constraints |
| Fuzzy logic | Combine uncertain evidence into interpretable risk categories | Membership rules require validation |
| Heuristic rules | Provide a baseline for investigation and risk assessment | Rules may be brittle or biased |
| Q-learning | Learn preferences over state-action pairs from reward feedback | Learning quality depends on states, rewards, and training data |
| Confusion matrix | Measure classification outcomes | Results depend on how the candidate population is defined |

These techniques do not all serve the same purpose. Graph traversal explores relationships, fuzzy logic represents uncertain evidence, heuristic rules provide deterministic decision-making, and reinforcement learning optimizes sequential actions based on rewards.

They should be compared using appropriate metrics and controlled experiments rather than treated as interchangeable algorithms.

---

## Reinforcement Learning Implementation

The `rl-agents/` module implements a tabular reinforcement learning pipeline for the fraudster and investigator roles.

### Q-learning

Q-learning estimates the expected long-term value of taking an action in a state.

A standard Q-learning update is:

\[
Q(s,a) \leftarrow Q(s,a) +
\alpha\left[r+\gamma\max_{a'}Q(s',a')-Q(s,a)\right]
\]

Where:

- \(Q(s,a)\) is the estimated value of taking action \(a\) in state \(s\).
- \(\alpha\) is the learning rate.
- \(r\) is the observed reward.
- \(\gamma\) is the discount factor.
- \(s'\) is the next state.
- \(\max_{a'}Q(s',a')\) is the best estimated next-state action value.

The implementation also supports terminal outcomes and delayed reward handling appropriate to its training pipeline.

### State abstraction

The agents do not learn directly over every possible database state. Instead, the state-abstraction module converts the environment into a more compact representation.

This reduces the size of the learning problem but can remove information that matters for distinguishing different companies or transaction paths.

The project uses role-specific state representations and compatibility metadata for saved policies.

### Fraudster agent

The fraudster agent chooses among legal financial actions, including transfers, routed transfers, split transfers, and waiting.

Its reward contract encourages the intended evasion objective, while successful detection is penalized. Reaching the turn limit without detection can earn a reward, with an additional reward when the financial objective is achieved.

These rewards are simulation objectives, not a claim that the policy has learned realistic criminal behavior.

### Investigator agent

The investigator learns preferences over investigative actions and company-flagging decisions.

The current investigator reward contract uses:

\[
R_{\text{investigator}} = TP - FP - FN
\]

Where:

- \(TP\): shell-company candidates correctly flagged.
- \(FP\): legitimate candidates incorrectly flagged.
- \(FN\): shell-company candidates not flagged.
- \(TN\): legitimate candidates not flagged.

True negatives contribute zero directly to this reward.

The investigator's training pipeline captures eligible legal `FLAG_COMPANY` candidates before decisions, deduplicates the candidate population, and evaluates their labels after the episode terminates. Training guards are intended to skip invalid, incomplete, empty, or single-class populations rather than publishing an update from an unsuitable episode.

### Separation of public observations and ground truth

The investigator is intended to operate on public scenario evidence, company information, transaction history, and sanitized action memory.

Ground-truth labels and private shell-company identifiers are reserved for the relevant fraudster context or for post-episode training and evaluation. They must not be supplied to the investigator as direct decision-time answers.

This separation is important because an agent that receives the answer in its observation is not meaningfully detecting fraud.

### Checkpoints and compatibility

Saved policies contain learned values and associated metadata. The training and managed-run code checks compatibility between the checkpoint and the expected agent configuration.

An older checkpoint may be rejected when its state representation, legal-action definition, or reward contract is incompatible with the current implementation.

Checkpoint compatibility does not guarantee that the policy performs well. A valid checkpoint can still represent a poorly trained policy.

---

## Reward Functions and Evaluation

The project uses different objectives for fraudster and investigator agents.

| Role | Intended objective | Example of a failure |
|---|---|---|
| Fraudster | Achieve the financial objective and evade detection | Funds fail to move or the investigator flags the relevant company |
| Investigator | Identify shell-company candidates while limiting incorrect flags and missed detections | Too many false alarms or failure to flag suspicious candidates |

### Classification metrics

For candidate classification, the project uses the following definitions:

\[
\text{Precision}=\frac{TP}{TP+FP}
\]

\[
\text{Recall}=\frac{TP}{TP+FN}
\]

\[
F1=2\cdot\frac{\text{Precision}\cdot\text{Recall}}
{\text{Precision}+\text{Recall}}
\]

The confusion matrix is:

| | Predicted shell candidate | Predicted non-shell candidate |
|---|---:|---:|
| Actual shell candidate | TP | FN |
| Actual legitimate candidate | FP | TN |

Precision measures how many flagged candidates were shell candidates. Recall measures how many shell candidates were identified. F1 combines precision and recall.

Metrics must be interpreted with their evaluation population in mind. In this project, the candidate-level evaluation has included legal `FLAG_COMPANY` candidates presented before investigator decisions. This is not equivalent to evaluating only companies that participated in the fraudster's actual transaction path.

### Current experimental status

The current implementation demonstrates the learning and evaluation pipeline, but the learned investigator has not consistently demonstrated useful detection performance.

In a documented ten-episode evaluation, the learned investigator had the following aggregate discovered-candidate results:

| Metric | Result |
|---|---:|
| True positives | 0 |
| False positives | 80 |
| True negatives | 400 |
| False negatives | 40 |

For the same evaluation, the learned investigator's source/target evaluation reported zero true positives and 20 false positives. A heuristic baseline reported zero false positives and 20 true negatives on that source/target evaluation.

These results are evidence of a weakness, not a success claim. The learned investigator was flagging candidates without correctly identifying the positive shell labels in that evaluation.

The fraudster training setup has also used a simple bot opponent that prioritizes direct transfers and otherwise waits. That provides limited exposure to routed or split-transfer behavior.

**The current experimental evidence does not establish that reinforcement learning outperforms the heuristic baseline, nor that the agents reliably detect fraud.** A stronger claim would require corrected training coverage, controlled comparisons, and repeated evaluation on unseen scenarios.

---

## Database and Data Model

PostgreSQL stores the application's persistent domain data.

The Java entity and repository layers model concepts including:

- Companies.
- Directors.
- Company-director relationships.
- Transactions and transaction origins.
- Fraud scenarios and turns.
- Fraudster actions and their targets.
- Investigator actions.

Spring Data repositories provide persistence access, while service classes implement business rules and scenario lifecycle operations.

The database is also relevant to the evaluation workflow. Reliable training and evaluation require a consistent relationship between decision-time candidate populations, terminal outcomes, and ground-truth labels.

Historical scenarios may not contain all the decision-time snapshots required for reliable retrospective evaluation. A missing snapshot must not be silently reconstructed and treated as if it were the original candidate population.

---

## Project Structure

```text
catchmeifyoucan/
├── .mvn/
├── mvnw
├── mvnw.cmd
├── pom.xml
├── rl-agents/
│   ├── README.md
│   ├── api_client.py
│   ├── client.py
│   ├── detection_metrics.py
│   ├── evaluate.py
│   ├── fraudster_bot.py
│   ├── ground_truth.py
│   ├── investigator_bot.py
│   ├── q_learning.py
│   ├── rl_policies.py
│   ├── rl_training.py
│   ├── run_episode.py
│   ├── run_heuristic_episode.py
│   ├── run_learned_episode.py
│   ├── state_abstraction.py
│   ├── test_*.py
│   └── reports/
├── src/
│   ├── main/
│   │   ├── java/catchmeifyoucan/
│   │   │   ├── controller/
│   │   │   ├── dto/
│   │   │   ├── entity/
│   │   │   ├── repository/
│   │   │   ├── service/
│   │   │   └── simulation/
│   │   └── resources/
│   │       └── static/
│   │           ├── index.html
│   │           ├── css/
│   │           └── js/
│   └── test/
│       ├── java/
│       └── js/
└── README.md
```

### Main components

- `controller/`: HTTP endpoints for companies, transactions, scenarios, and agent actions.
- `dto/`: Request and response objects used by the API.
- `entity/`: Persistent domain models.
- `repository/`: Database access interfaces.
- `service/`: Business logic, action validation, investigation, and lifecycle management.
- `simulation/`: Synthetic company, director, and transaction generation.
- `static/`: Browser interface and risk-analyzer frontend.
- `rl-agents/`: Python agents, Q-learning, state abstractions, training, evaluation, and tests.

The exact set of generated reports and saved checkpoints may change as experiments evolve. Large temporary training artifacts are not required for the basic Java application unless a particular workflow explicitly loads them.

---

## Getting Started

### Prerequisites

Install the following:

1. A compatible JDK.
2. PostgreSQL.
3. Git.
4. Python compatible with the scripts in `rl-agents/` if you want to run the RL agents.

The Maven Wrapper is included, so a separate Maven installation is generally unnecessary.

### 1. Clone the repository

```bash
git clone https://github.com/subhrojit-byte/catchmeifyoucan.git
cd catchmeifyoucan
```

### 2. Create a PostgreSQL database

Create a dedicated local database for the project.

For example, using the PostgreSQL command-line client:

```sql
CREATE DATABASE catchmeifyoucan;
```

Use a dedicated local database account with the permissions needed by the application. Configure the database schema according to the project's JPA and application configuration.

Do not point the application at a production database or a database containing sensitive financial data.

### 3. Configure the database connection

Configure the following environment variables for the application:

| Variable | Purpose |
|---|---|
| `DB_URL` | JDBC URL for the PostgreSQL database |
| `DB_USERNAME` | Database username |
| `DB_PASSWORD` | Database password |
| `CATCHMEIFYOUCAN_BASE_URL` | Base URL used by the Python agent client, normally `http://localhost:8080` |

Example PowerShell configuration for a local development session:

```powershell
$env:DB_URL = "jdbc:postgresql://localhost:5432/catchmeifyoucan"
$env:DB_USERNAME = "your_local_database_user"
$env:DB_PASSWORD = "your_local_database_password"
$env:CATCHMEIFYOUCAN_BASE_URL = "http://localhost:8080"
```

Replace the example credentials with your own local values.

These commands set environment variables only for the current PowerShell process and its child processes. Set them before starting the application.

**Never commit real passwords, access tokens, private database URLs, or local secret configuration files.** The repository's `.gitignore` excludes local application configuration and environment files.

If a variable is not recognized, inspect `src/main/resources/application.properties` locally and confirm how the current Spring configuration maps environment variables.

### 4. Start the Spring Boot application

From the repository root, run:

```powershell
.\mvnw.cmd spring-boot:run
```

Alternatively, build the application:

```powershell
.\mvnw.cmd clean package
```

Then run the generated JAR from the appropriate `target/` path:

```powershell
java -jar target/<generated-jar-name>.jar
```

Use the actual JAR filename produced by the build. If the build fails, resolve the reported Java, Maven, dependency, or database configuration error before continuing.

### 5. Open the frontend

With the application running on the default port, open:

http://localhost:8080/

The static frontend is served by Spring Boot. Create a scenario and use the available controls to inspect companies, transaction activity, and the investigator workflow.

---

## Configuration

### Environment variables

The database variables and agent base URL described above are relevant to local execution.

The evaluation workflow can also use:

| Variable | Purpose |
|---|---|
| `CATCHMEIFYOUCAN_EVALUATOR_DATABASE_URL` | Database URL for the separate evaluator workflow, where supported |

The evaluator should use a read-only database connection when it only needs to inspect persisted data.

The evaluator's database access requirements are separate from the main application's datasource configuration. Setting the evaluator variable does not, by itself, guarantee that historical scenarios contain enough information for valid retrospective evaluation.

### Local configuration files

Keep local configuration files out of version control. If you add a new configuration file, check whether it contains credentials and ensure that the ignore rules cover it before staging.

For public contributions, document required configuration using placeholders rather than actual secrets.

---

## Running the Python Agents

The Python agent module is maintained separately from the Java application.

Before running a training or evaluation command:

1. Start the Spring Boot application.
2. Confirm that the configured API base URL is reachable.
3. Configure the Python environment according to `rl-agents/README.md`.
4. Inspect the supported command-line options of the relevant script.
5. Confirm that the database and scenario population are suitable for the intended experiment.

The principal scripts include:

| Script | Responsibility |
|---|---|
| `client.py` | Client communication with the application |
| `api_client.py` | API client functionality |
| `q_learning.py` | Q-learning implementation |
| `state_abstraction.py` | Compact agent state representations |
| `rl_policies.py` | Policy and checkpoint handling |
| `rl_training.py` | Training logic |
| `run_episode.py` | Episode execution |
| `run_learned_episode.py` | Learned-policy episode execution |
| `run_heuristic_episode.py` | Heuristic baseline execution |
| `evaluate.py` | Evaluation and metric reporting |
| `detection_metrics.py` | Detection metric calculations |
| `ground_truth.py` | Ground-truth access for the appropriate training/evaluation workflows |
| `fraudster_bot.py` | Fraudster bot policy |
| `investigator_bot.py` | Investigator bot policy |

The scripts' supported arguments and checkpoint requirements are defined in the code and the agent-specific README.

Do not assume that an existing checkpoint is compatible with the current policy implementation. Check the compatibility metadata before using it for an experiment.

---

## Testing

The repository includes Java, Python, and JavaScript tests.

### Java tests

Run the Java test suite using:

```powershell
.\mvnw.cmd test
```

Tests cover parts of the scenario lifecycle, action handling, service behavior, controller behavior, and information boundaries.

Some integration tests may require a correctly configured database or additional test configuration.

### Python tests

From the `rl-agents` directory, run:

```powershell
python -m unittest discover -v
```

Use the Python interpreter and dependency environment required by the project. If the repository's test setup specifies additional dependencies or commands, follow `rl-agents/README.md`.

### JavaScript tests

The frontend tests use Node.js and the built-in test runner:

```powershell
node --test src/test/js/*.test.cjs
```

### Testing versus model quality

Passing software tests shows that tested code paths satisfy their assertions. It does not prove that a learned policy generalizes to unseen scenarios or achieves useful fraud-detection accuracy.

Model quality requires separate experiments, meaningful baselines, and reproducible evaluation.

---

## Current Limitations and Weaknesses

This section is intentionally explicit. These are important constraints when interpreting the current project.

### 1. Reinforcement learning performance is not yet reliable

The investigator's documented evaluation produced zero true positives in the ten-episode discovered-candidate evaluation, alongside 80 false positives and 40 false negatives.

This means the current learned investigator did not successfully identify the positive shell labels in that evaluation and also flagged legitimate candidates.

The existence of a trained checkpoint is not evidence of successful learning. The current results do not justify claiming that the learned investigator is more accurate than the heuristic baseline.

### 2. The fraudster training opponent is too simple

The investigator-only training setup has used a bot that prioritizes direct transfers and otherwise waits.

That opponent does not adequately expose the investigator to the full range of behaviors represented by routed and split transfers. As a result, the investigator may not learn to respond effectively to more varied transaction paths.

Training against a narrow opponent can produce a policy that performs well only in the limited environment it has experienced.

### 3. Candidate detection is not the same as fraud-path detection

The investigator's current candidate-level metrics evaluate shell-company candidates that were legally available for flagging before investigator decisions.

A shell-company candidate can exist in the evaluation population without participating in the actual fraudulent transaction path.

Consequently, the current metrics do not establish that the investigator can identify the specific companies used to move the fraudster's funds.

Future evaluation should separately measure:

- Shell-candidate classification.
- Source and target identification.
- Intermediary identification.
- Detection of companies actually used in the transaction path.
- Successful investigation outcomes and financial loss prevention.

### 4. The reward function has limitations

The investigator reward uses \(TP-FP-FN\), with true negatives contributing zero directly.

This objective penalizes false alarms and missed positives, but its effectiveness depends on the candidate population, episode construction, and the distribution of positive and negative examples.

Sparse or delayed feedback can make learning difficult. A poor state representation or weak training opponent can also result in negative Q-values or policies that repeatedly choose unhelpful actions.

The reward function should be evaluated empirically rather than assumed to be optimal.

### 5. State abstraction loses information

Tabular Q-learning relies on a compact state representation. Different real-world situations can map to the same abstract state even when the correct actions differ.

The current representation is much smaller than the full company and transaction network. This makes the learning problem manageable, but can limit the ability to reason about complex paths, long histories, and previously unseen combinations of evidence.

### 6. Synthetic data does not represent the full complexity of real fraud

Shell-company examples are generated using predefined characteristics, and background transactions are simulated.

Real companies can share directors, addresses, or service providers for legitimate reasons. Conversely, real fraud can occur without obvious shell-company characteristics.

The simulation therefore cannot establish real-world detection accuracy, fairness, or operational suitability.

### 7. Risk scores are not calibrated fraud probabilities

The fuzzy risk analyzer produces a score from the rules and evidence it receives.

A score of 80/100 does not automatically mean an 80% probability of fraud. The score is not a substitute for calibration against representative, independently labeled real-world data.

Missing-data fallbacks also need careful interpretation. A neutral score represents an unavailable-information policy, not evidence of low or moderate risk.

### 8. Evaluation depends on reliable data snapshots

A valid evaluation requires knowing which companies could legally be flagged at each decision point and what their labels were.

Historical database records may not preserve all the decision-time candidate snapshots required for accurate retrospective evaluation. Reconstructing candidates from later state can introduce errors or leakage.

When the required data is absent, the evaluation should report the limitation rather than invent a complete historical population.

### 9. Generalization has not been established

A policy may perform differently when company profiles, transaction networks, action sequences, or random seeds change.

The current experiments are not sufficient to establish robust performance across unseen networks, different fraud strategies, or realistic class distributions.

Repeated evaluation, held-out scenarios, baseline comparisons, and ablation studies are necessary before drawing stronger conclusions.

### 10. The simulation is not a production financial platform

The application is an academic prototype. It has not been established as suitable for real financial monitoring, regulatory reporting, automated account restrictions, or deployment in a live banking environment.

Production use would require substantially more validation, security controls, operational monitoring, data governance, and human oversight.

---

## Security and Privacy Considerations

The application should be run locally with synthetic data for demonstrations and experiments.

- Keep database credentials in local environment variables or private configuration.
- Do not publish real secrets in source files, logs, checkpoints, or evaluation artifacts.
- Use read-only database access for workflows that only inspect historical data.
- Keep ground-truth labels and private fraudster context out of investigator decision-time observations.
- Do not interpret a risk score as proof of criminal activity.
- Avoid using real personal or financial information without appropriate authorization, privacy controls, and legal review.

The presence of credential-handling services or information-boundary tests does not, by itself, constitute a comprehensive security audit.

---

## Future Improvements

The following are potential improvements, not claims about currently completed functionality.

### Reinforcement learning

- Train the investigator against a more varied opponent that performs direct, routed, and split transfers.
- Use multiple random seeds and held-out scenario networks.
- Compare the learned policy with simple and stronger heuristic baselines.
- Investigate state representations that preserve more useful path and transaction information.
- Review reward scaling and delayed-credit assignment.
- Track training reward, episode success, precision, recall, F1, false-positive rate, and path-level detection separately.
- Verify checkpoint compatibility and evaluation provenance for every reported result.

### Evaluation methodology

- Persist the exact legal candidate population at each investigator decision.
- Preserve a reliable mapping between candidates, decisions, transaction paths, and ground-truth labels.
- Separate candidate-level metrics from transaction-path detection metrics.
- Report uncertainty across repeated experiments.
- Prevent information leakage from terminal labels or private agent context.
- Make baseline and learned-policy comparisons use equivalent scenarios and evaluation populations.

### Graph analysis and fuzzy logic

- Compare BFS and DFS strategies under explicitly defined path constraints.
- Explore path-level features and transaction timing.
- Validate fuzzy membership functions and rule weights against a suitable labeled dataset.
- Test the effects of missing data and shared legitimate business relationships.
- Calibrate risk outputs if reliable representative labels become available.

### Software and user experience

- Improve reproducibility of local setup and training commands.
- Document API requests and responses.
- Improve visualization of actual transaction paths and investigator evidence.
- Add repeatable experiment configurations and concise evaluation reports.
- Expand integration tests and deployment documentation if the project scope grows.

---

## Academic Scope

CatchMeIfYouCan is intended to demonstrate how software engineering and AI techniques can be combined in an interactive fraud-investigation simulation.

It provides a practical environment for studying:

- Graph traversal and relationship analysis.
- Fuzzy logic and uncertain evidence.
- Rule-based reasoning and heuristic baselines.
- Reinforcement learning and reward design.
- State abstraction and action selection.
- Precision, recall, F1-score, and confusion-matrix analysis.
- The difference between a working learning pipeline and a policy that actually learns a useful strategy.

An important finding from the current implementation is that **implementing reinforcement learning is not the same as demonstrating successful reinforcement learning**. The quality of the observations, reward design, training opponent, evaluation population, and baseline all matter.

This makes the project's limitations an important part of its experimental results, rather than something to hide behind a polished interface.

## Contributing

Contributions and suggestions are welcome.

For proposed changes:

1. Describe the problem or improvement.
2. Keep changes consistent with the existing Java/Python architecture.
3. Add or update tests where appropriate.
4. Avoid introducing credentials or private data.
5. Report experimental results with the evaluation population and metric definitions.
6. Distinguish observed results from hypotheses or planned improvements.

## License

No license is specified here. Add an appropriate `LICENSE` file before explicitly granting permission for others to reuse, modify, or redistribute the project.
