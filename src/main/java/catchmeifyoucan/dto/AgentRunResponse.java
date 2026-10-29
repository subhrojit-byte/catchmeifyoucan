package catchmeifyoucan.dto;

import tools.jackson.databind.JsonNode;

import java.util.List;

public record AgentRunResponse(
        String runId,
        Long scenarioId,
        String status,
        String currentAgent,
        Integer pausedAfterRound,
        JsonNode latestAction,
        JsonNode scenarioState,
        JsonNode latestEvidence,
        JsonNode finalState,
        Integer actionsAttempted,
        String message,
        List<JsonNode> events) {
}
