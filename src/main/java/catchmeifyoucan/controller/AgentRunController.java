package catchmeifyoucan.controller;

import catchmeifyoucan.dto.AgentRunResponse;
import catchmeifyoucan.dto.AgentRunStartRequest;
import catchmeifyoucan.service.AgentRunService;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

@RestController
@RequestMapping("/api/agent-runs")
public class AgentRunController {
    private final AgentRunService agentRunService;

    public AgentRunController(AgentRunService agentRunService) {
        this.agentRunService = agentRunService;
    }

    @PostMapping
    public ResponseEntity<?> start(@RequestBody(required = false) AgentRunStartRequest request) {
        if (request == null || request.scenarioId() == null || request.scenarioId() <= 0) {
            return ResponseEntity.badRequest().body(Map.of("message", "A positive scenarioId is required."));
        }
        String mode = request.mode() == null || request.mode().isBlank()
                ? "INFERENCE" : request.mode().trim().toUpperCase(java.util.Locale.ROOT);
        if (!mode.equals("INFERENCE") && !mode.equals("TRAIN_FRAUDSTER")
                && !mode.equals("TRAIN_INVESTIGATOR") && !mode.equals("HUMAN_FRAUDSTER")
                && !mode.equals("HEURISTIC_SEARCH")) {
            return ResponseEntity.badRequest().body(Map.of(
                    "message", "mode must be INFERENCE, TRAIN_FRAUDSTER, TRAIN_INVESTIGATOR, HUMAN_FRAUDSTER, or HEURISTIC_SEARCH."));
        }
        try {
            if (!mode.equals("TRAIN_INVESTIGATOR") && request.investigatorCheckpoint() != null) {
                return ResponseEntity.badRequest().body(Map.of(
                        "message", "investigatorCheckpoint is valid only with TRAIN_INVESTIGATOR."));
            }
            AgentRunResponse response = switch (mode) {
                case "TRAIN_FRAUDSTER" -> agentRunService.startFraudsterTraining(request.scenarioId());
                case "TRAIN_INVESTIGATOR" -> agentRunService.startInvestigatorTraining(
                        request.scenarioId(), request.investigatorCheckpoint());
                case "HUMAN_FRAUDSTER" -> agentRunService.startHumanFraudsterMatch(request.scenarioId());
                case "HEURISTIC_SEARCH" -> agentRunService.startHeuristicSearch(request.scenarioId());
                default -> agentRunService.start(request.scenarioId());
            };
            return ResponseEntity.accepted().body(response);
        } catch (AgentRunService.AgentRunNotFoundException error) {
            return ResponseEntity.status(HttpStatus.NOT_FOUND).body(Map.of("message", error.getMessage()));
        } catch (AgentRunService.AgentRunConflictException error) {
            return ResponseEntity.status(HttpStatus.CONFLICT).body(Map.of("message", error.getMessage()));
        } catch (IllegalStateException error) {
            return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE)
                    .body(Map.of("message", error.getMessage()));
        } catch (IllegalArgumentException error) {
            return ResponseEntity.badRequest().body(Map.of("message", error.getMessage()));
        }
    }

    @GetMapping("/{runId}")
    public ResponseEntity<?> get(@PathVariable String runId) {
        try {
            AgentRunResponse response = agentRunService.get(runId);
            return ResponseEntity.ok(response);
        } catch (AgentRunService.AgentRunNotFoundException error) {
            return ResponseEntity.status(HttpStatus.NOT_FOUND).body(Map.of("message", error.getMessage()));
        }
    }

    @PostMapping("/{runId}/continue")
    public ResponseEntity<?> continueRun(@PathVariable String runId) {
        try {
            return ResponseEntity.ok(agentRunService.continueRun(runId));
        } catch (AgentRunService.AgentRunNotFoundException error) {
            return ResponseEntity.status(HttpStatus.NOT_FOUND).body(Map.of("message", error.getMessage()));
        } catch (AgentRunService.AgentRunConflictException error) {
            return ResponseEntity.status(HttpStatus.CONFLICT).body(Map.of("message", error.getMessage()));
        }
    }

    @PostMapping("/{runId}/cancel")
    public ResponseEntity<?> cancel(@PathVariable String runId) {
        try {
            return ResponseEntity.ok(agentRunService.cancel(runId));
        } catch (AgentRunService.AgentRunNotFoundException error) {
            return ResponseEntity.status(HttpStatus.NOT_FOUND).body(Map.of("message", error.getMessage()));
        } catch (AgentRunService.AgentRunConflictException error) {
            return ResponseEntity.status(HttpStatus.CONFLICT).body(Map.of("message", error.getMessage()));
        }
    }
}
