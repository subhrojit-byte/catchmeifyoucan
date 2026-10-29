"""Small, deterministic tabular Q-learning implementation.

The implementation intentionally uses only the Python standard library. State
and action keys are supplied by the environment and should already be compact
and free of hidden evaluator information.
"""

from __future__ import annotations

import json
import hashlib
import math
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from state_abstraction import (
    INVESTIGATOR_STATE_ABSTRACTION_VERSION,
    LEGAL_ACTION_SCHEMA_VERSION,
    STATE_ABSTRACTION_VERSION,
)


def _key(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def checkpoint_compatibility(policy_role: str) -> dict[str, str]:
    if policy_role not in {"fraudster", "investigator"}:
        raise ValueError("policy_role must be fraudster or investigator.")
    return {
        "policy_role": policy_role,
        "state_abstraction_version": (
            STATE_ABSTRACTION_VERSION if policy_role == "fraudster"
            else INVESTIGATOR_STATE_ABSTRACTION_VERSION
        ),
        "legal_action_schema_version": LEGAL_ACTION_SCHEMA_VERSION,
        "observation_reward_contract_version": (
            "observation-reward-contract-v2" if policy_role == "fraudster"
            else "investigator-fraud-path-reward-contract-v1"
        ),
        "private_shell_knowledge_features": (
            "run-authorized-shell-intermediary-ids-v1" if policy_role == "fraudster"
            else "not-applicable"
        ),
    }


def ensure_policy_compatibility(learner: Any, policy_role: str) -> None:
    """Attach or validate role metadata for a writable learner."""
    expected = checkpoint_compatibility(policy_role)
    if not isinstance(learner, QLearningAgent):
        return
    if learner.compatibility is None:
        learner.compatibility = expected
    elif learner.compatibility != expected:
        raise ValueError(f"Learner compatibility metadata does not match {policy_role} role.")


@dataclass
class QLearningAgent:
    learning_rate: float = 0.1
    discount_factor: float = 0.95
    epsilon: float = 0.1
    seed: int = 0
    q_values: dict[str, dict[str, float]] = field(default_factory=dict)
    training_steps: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    compatibility: dict[str, str] | None = None

    def __post_init__(self) -> None:
        if not 0 <= self.learning_rate <= 1:
            raise ValueError("learning_rate must be between 0 and 1.")
        if not 0 <= self.discount_factor <= 1:
            raise ValueError("discount_factor must be between 0 and 1.")
        if not 0 <= self.epsilon <= 1:
            raise ValueError("epsilon must be between 0 and 1.")
        if self.compatibility is not None:
            self._validate_compatibility(self.compatibility)
        self._random = random.Random(self.seed)

    @classmethod
    def for_role(cls, policy_role: str, **kwargs: Any) -> "QLearningAgent":
        kwargs["compatibility"] = checkpoint_compatibility(policy_role)
        return cls(**kwargs)

    @staticmethod
    def _validate_compatibility(value: Any) -> None:
        required = {
            "policy_role", "state_abstraction_version", "legal_action_schema_version",
            "observation_reward_contract_version", "private_shell_knowledge_features",
        }
        if not isinstance(value, dict) or set(value) != required:
            raise ValueError(
                "Checkpoint compatibility metadata must contain exactly: "
                "policy_role, state_abstraction_version, legal_action_schema_version, "
                "observation_reward_contract_version, private_shell_knowledge_features."
            )
        if value["policy_role"] not in {"fraudster", "investigator"}:
            raise ValueError("Checkpoint policy_role must be fraudster or investigator.")
        if any(not isinstance(value[field], str) or not value[field] for field in required - {"policy_role"}):
            raise ValueError("Checkpoint compatibility versions must be non-empty strings.")

    def select_action(self, state: Any, actions: Iterable[Any]) -> Any:
        return self._select_action(state, actions, initialize=True)

    def select_action_with_diagnostics(
        self, state: Any, actions: Iterable[Any]
    ) -> tuple[Any, dict[str, Any]]:
        """Select normally and return index-based diagnostics without action IDs."""
        return self._select_action_detailed(state, actions, initialize=True)

    def select_action_read_only(
        self,
        state: Any,
        actions: Iterable[Any],
        *,
        epsilon: float | None = None,
        rng: random.Random | None = None,
    ) -> Any:
        """Select from a policy table without adding unseen entries."""
        return self._select_action(
            state, actions, initialize=False, epsilon=epsilon, rng=rng
        )

    def select_action_read_only_with_diagnostics(
        self,
        state: Any,
        actions: Iterable[Any],
        *,
        epsilon: float | None = None,
        rng: random.Random | None = None,
    ) -> tuple[Any, dict[str, Any]]:
        return self._select_action_detailed(
            state, actions, initialize=False, epsilon=epsilon, rng=rng
        )

    def _select_action(
        self,
        state: Any,
        actions: Iterable[Any],
        *,
        initialize: bool,
        epsilon: float | None = None,
        rng: random.Random | None = None,
    ) -> Any:
        action, _ = self._select_action_detailed(
            state, actions, initialize=initialize, epsilon=epsilon, rng=rng
        )
        return action

    def _select_action_detailed(
        self,
        state: Any,
        actions: Iterable[Any],
        *,
        initialize: bool,
        epsilon: float | None = None,
        rng: random.Random | None = None,
    ) -> tuple[Any, dict[str, Any]]:
        choices = list(actions)
        if not choices:
            raise ValueError("At least one legal action is required.")
        state_key = _key(state)
        values = self.q_values.setdefault(state_key, {}) if initialize else self.q_values.get(state_key, {})
        action_keys = [_key(action) for action in choices]
        if initialize:
            for action_key in action_keys:
                values.setdefault(action_key, 0.0)
        exploration_rate = self.epsilon if epsilon is None else epsilon
        random_source = self._random if rng is None else rng
        if not 0 <= exploration_rate <= 1:
            raise ValueError("epsilon must be between 0 and 1.")
        q_values = [float(values.get(action_key, 0.0)) for action_key in action_keys]
        best_value = max(q_values)
        best = [index for index, value in enumerate(q_values) if value == best_value]
        if random_source.random() < exploration_rate:
            selected_index = random_source.randrange(len(choices))
            selection_mode = "epsilon_exploration"
            tie_breaking = "not_applicable"
        else:
            # Stable tie-breaking keeps an untrained policy reproducible; epsilon
            # remains the explicit source of exploration.
            selected_index = best[0]
            selection_mode = "greedy"
            tie_breaking = "first_legal_max_q" if len(best) > 1 else "unique_max_q"
        return choices[selected_index], {
            "q_values": q_values,
            "selected_index": selected_index,
            "max_q_indices": best,
            "selection_mode": selection_mode,
            "tie_breaking": tie_breaking,
        }

    def reseed(self, seed: int) -> None:
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ValueError("seed must be an integer.")
        self.seed = seed
        self._random = random.Random(seed)

    def update(
        self,
        state: Any,
        action: Any,
        reward: float,
        next_state: Any | None,
        next_actions: Iterable[Any] = (),
        *,
        done: bool = False,
    ) -> float:
        state_key = _key(state)
        action_key = _key(action)
        values = self.q_values.setdefault(state_key, {})
        old_value = values.get(action_key, 0.0)
        if done or next_state is None:
            target = float(reward)
        else:
            next_values = self.q_values.setdefault(_key(next_state), {})
            next_keys = [_key(item) for item in next_actions]
            if next_keys:
                target = float(reward) + self.discount_factor * max(
                    next_values.get(item, 0.0) for item in next_keys
                )
            else:
                target = float(reward)
        new_value = old_value + self.learning_rate * (target - old_value)
        values[action_key] = new_value
        self.training_steps += 1
        return new_value

    def save(self, path: str | Path) -> None:
        Path(path).write_text(
            json.dumps(self._checkpoint_payload(), indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def save_new(self, path: str | Path) -> None:
        """Write a fresh checkpoint without replacing a file created by another run."""
        checkpoint_path = Path(path)
        created = False
        try:
            with checkpoint_path.open("x", encoding="utf-8") as checkpoint_file:
                created = True
                json.dump(self._checkpoint_payload(), checkpoint_file, indent=2, sort_keys=True)
        except Exception:
            # The exclusive open means an existing checkpoint is never ours to remove.
            if created and checkpoint_path.exists():
                try:
                    checkpoint_path.unlink()
                except OSError:
                    pass
            raise

    def _checkpoint_payload(self) -> dict[str, Any]:
        return {
            "format": 1,
            "learning_rate": self.learning_rate,
            "discount_factor": self.discount_factor,
            "epsilon": self.epsilon,
            "seed": self.seed,
            "training_steps": self.training_steps,
            "metadata": self.metadata,
            "q_values": self.q_values,
            "compatibility": self.compatibility,
        }

    @classmethod
    def load(cls, path: str | Path) -> "QLearningAgent":
        try:
            checkpoint_bytes = Path(path).read_bytes()
            payload = json.loads(checkpoint_bytes.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("Invalid Q-learning checkpoint JSON.") from error
        if not isinstance(payload, dict) or payload.get("format") != 1:
            raise ValueError("Unsupported Q-learning policy format.")

        required = {
            "learning_rate", "discount_factor", "epsilon", "seed",
            "training_steps", "metadata", "q_values",
        }
        missing = required.difference(payload)
        if missing:
            raise ValueError(
                "Q-learning checkpoint is missing fields: "
                + ", ".join(sorted(missing))
            )
        compatibility = payload.get("compatibility")
        if compatibility is not None:
            cls._validate_compatibility(compatibility)

        def finite_number(name: str) -> float:
            value = payload[name]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"Checkpoint field {name!r} must be numeric.")
            if not math.isfinite(float(value)):
                raise ValueError(f"Checkpoint field {name!r} must be finite.")
            return float(value)

        learning_rate = finite_number("learning_rate")
        discount_factor = finite_number("discount_factor")
        epsilon = finite_number("epsilon")
        if not 0 <= learning_rate <= 1:
            raise ValueError("Checkpoint learning_rate must be between 0 and 1.")
        if not 0 <= discount_factor <= 1:
            raise ValueError("Checkpoint discount_factor must be between 0 and 1.")
        if not 0 <= epsilon <= 1:
            raise ValueError("Checkpoint epsilon must be between 0 and 1.")

        seed = payload["seed"]
        training_steps = payload["training_steps"]
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ValueError("Checkpoint seed must be an integer.")
        if (isinstance(training_steps, bool) or not isinstance(training_steps, int)
                or training_steps < 0):
            raise ValueError("Checkpoint training_steps must be a non-negative integer.")
        if not isinstance(payload["metadata"], dict):
            raise ValueError("Checkpoint metadata must be an object.")
        raw_q_values = payload["q_values"]
        if not isinstance(raw_q_values, dict):
            raise ValueError("Checkpoint q_values must be an object.")
        q_values: dict[str, dict[str, float]] = {}
        for state_key, actions in raw_q_values.items():
            if not isinstance(state_key, str) or not isinstance(actions, dict):
                raise ValueError("Checkpoint Q-values must map string states to objects.")
            q_values[state_key] = {}
            for action_key, value in actions.items():
                if not isinstance(action_key, str):
                    raise ValueError("Checkpoint action keys must be strings.")
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError("Checkpoint Q-values must be numeric.")
                if not math.isfinite(float(value)):
                    raise ValueError("Checkpoint Q-values must be finite.")
                q_values[state_key][action_key] = float(value)

        agent = cls(
            learning_rate=learning_rate,
            discount_factor=discount_factor,
            epsilon=epsilon,
            seed=seed,
            q_values=q_values,
            training_steps=training_steps,
            metadata=dict(payload["metadata"]),
            compatibility=dict(compatibility) if compatibility is not None else None,
        )
        # Runtime-only provenance is derived from the same bytes used to parse
        # the model and is deliberately excluded from saved checkpoint payloads.
        agent._loaded_checkpoint_path = Path(path).resolve()
        agent._loaded_checkpoint_sha256 = hashlib.sha256(checkpoint_bytes).hexdigest()
        return agent


class ReadOnlyQLearningAgent:
    """Evaluation adapter that cannot mutate a loaded Q-table."""

    def __init__(self, learner: QLearningAgent, *, seed: int = 0):
        self._learner = learner
        self._random = random.Random(seed)

    def select_action(self, state: Any, actions: Iterable[Any]) -> Any:
        # Evaluation is greedy and deterministic. Keep the evaluation RNG
        # separate so evaluation never consumes the checkpoint learner's RNG.
        return self._learner.select_action_read_only(
            state, actions, epsilon=0.0, rng=self._random
        )

    def select_action_with_diagnostics(
        self, state: Any, actions: Iterable[Any]
    ) -> tuple[Any, dict[str, Any]]:
        return self._learner.select_action_read_only_with_diagnostics(
            state, actions, epsilon=0.0, rng=self._random
        )

