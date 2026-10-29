package catchmeifyoucan.controller;

import catchmeifyoucan.dto.AgentRunResponse;
import catchmeifyoucan.dto.AgentRunStartRequest;
import catchmeifyoucan.service.AgentRunService;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class AgentRunControllerTest {
    @Test
    void startsAnExistingScenarioRunAndReturnsAccepted() {
        AgentRunService service = mock(AgentRunService.class);
        AgentRunResponse run = new AgentRunResponse(
                "run-123", 42L, "RUNNING", null, null, null, null, null, null, null, null, List.of()
        );
        when(service.start(42L)).thenReturn(run);

        var response = new AgentRunController(service).start(new AgentRunStartRequest(42L));

        assertEquals(HttpStatus.ACCEPTED, response.getStatusCode());
        assertEquals(run, response.getBody());
    }

    @Test
    void startsFraudsterTrainingOnlyForExplicitTrainingMode() {
        AgentRunService service = mock(AgentRunService.class);
        AgentRunResponse run = new AgentRunResponse(
                "run-training", 42L, "RUNNING", null, null, null, null, null, null, null, null, List.of()
        );
        when(service.startFraudsterTraining(42L)).thenReturn(run);

        var response = new AgentRunController(service).start(
                new AgentRunStartRequest(42L, "TRAIN_FRAUDSTER"));

        assertEquals(HttpStatus.ACCEPTED, response.getStatusCode());
        assertEquals(run, response.getBody());
    }

    @Test
    void startsInvestigatorTrainingWithExplicitResumeCheckpoint() {
        AgentRunService service = mock(AgentRunService.class);
        AgentRunResponse run = new AgentRunResponse(
                "run-investigator", 42L, "RUNNING", null, null, null, null, null, null, null, null, List.of()
        );
        when(service.startInvestigatorTraining(42L, "rl-agents/first.json")).thenReturn(run);

        var response = new AgentRunController(service).start(new AgentRunStartRequest(
                42L, "TRAIN_INVESTIGATOR", "rl-agents/first.json"));

        assertEquals(HttpStatus.ACCEPTED, response.getStatusCode());
        assertEquals(run, response.getBody());
    }

    @Test
    void startsHumanFraudsterModeThroughManagedMatchLifecycle() {
        AgentRunService service = mock(AgentRunService.class);
        AgentRunResponse run = new AgentRunResponse(
                "run-human", 42L, "RUNNING", null, null, null, null, null, null, null, null, List.of()
        );
        when(service.startHumanFraudsterMatch(42L)).thenReturn(run);

        var response = new AgentRunController(service).start(
                new AgentRunStartRequest(42L, "HUMAN_FRAUDSTER"));

        assertEquals(HttpStatus.ACCEPTED, response.getStatusCode());
        assertEquals(run, response.getBody());
    }

    @Test
    void startsHeuristicSearchThroughItsSeparateManagedMode() {
        AgentRunService service = mock(AgentRunService.class);
        AgentRunResponse run = new AgentRunResponse(
                "run-heuristic", 42L, "RUNNING", null, null, null, null, null, null, null, null, List.of()
        );
        when(service.startHeuristicSearch(42L)).thenReturn(run);

        var response = new AgentRunController(service).start(
                new AgentRunStartRequest(42L, "HEURISTIC_SEARCH"));

        assertEquals(HttpStatus.ACCEPTED, response.getStatusCode());
        assertEquals(run, response.getBody());
    }

    @Test
    void rejectsUnknownRunMode() {
        AgentRunService service = mock(AgentRunService.class);

        var response = new AgentRunController(service).start(
                new AgentRunStartRequest(42L, "TRAIN_WITH_LABELS"));

        assertEquals(HttpStatus.BAD_REQUEST, response.getStatusCode());
    }

    @Test
    void rejectsAnAlreadyControlledScenario() {
        AgentRunService service = mock(AgentRunService.class);
        when(service.start(42L)).thenThrow(
                new AgentRunService.AgentRunConflictException("A run is already active.")
        );

        var response = new AgentRunController(service).start(new AgentRunStartRequest(42L));

        assertEquals(HttpStatus.CONFLICT, response.getStatusCode());
    }

    @Test
    void continueEndpointResumesPausedRun() {
        AgentRunService service = mock(AgentRunService.class);
        AgentRunResponse run = new AgentRunResponse(
                "run-123", 42L, "RUNNING", "FRAUDSTER", null,
                null, null, null, null, null, null, List.of()
        );
        when(service.continueRun("run-123")).thenReturn(run);

        var response = new AgentRunController(service).continueRun("run-123");

        assertEquals(HttpStatus.OK, response.getStatusCode());
        assertEquals("RUNNING", ((AgentRunResponse) response.getBody()).status());
    }

    @Test
    void cancelEndpointReturnsFailedRunState() {
        AgentRunService service = mock(AgentRunService.class);
        AgentRunResponse run = new AgentRunResponse(
                "run-123", 42L, "FAILED", null, null,
                null, null, null, null, null, "Learned-agent run cancelled by the user.", List.of()
        );
        when(service.cancel("run-123")).thenReturn(run);

        var response = new AgentRunController(service).cancel("run-123");

        assertEquals(HttpStatus.OK, response.getStatusCode());
        assertEquals("FAILED", ((AgentRunResponse) response.getBody()).status());
    }
}
