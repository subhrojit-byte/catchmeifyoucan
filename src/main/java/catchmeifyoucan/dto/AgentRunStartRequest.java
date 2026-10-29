package catchmeifyoucan.dto;

public record AgentRunStartRequest(Long scenarioId, String mode, String investigatorCheckpoint) {
    public AgentRunStartRequest(Long scenarioId) {
        this(scenarioId, null, null);
    }
    public AgentRunStartRequest(Long scenarioId, String mode) {
        this(scenarioId, mode, null);
    }
}
