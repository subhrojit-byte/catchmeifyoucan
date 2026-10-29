package catchmeifyoucan.controller;

import catchmeifyoucan.service.InvestigatorTrainingPreflightService;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/** Read-only managed readiness endpoint; never returns private shell context. */
@RestController
@RequestMapping("/api/agent-runs")
public class InvestigatorTrainingPreflightController {
    private final InvestigatorTrainingPreflightService preflightService;

    public InvestigatorTrainingPreflightController(InvestigatorTrainingPreflightService preflightService) {
        this.preflightService = preflightService;
    }

    @GetMapping("/investigator-training-preflight/{scenarioId}")
    public ResponseEntity<Map<String, Boolean>> preflight(@PathVariable long scenarioId) {
        try {
            return ResponseEntity.ok(Map.of(
                    "ready", preflightService.hasLegalAuthorizedShellRoute(scenarioId)));
        } catch (RuntimeException error) {
            return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE)
                    .body(Map.of("ready", false));
        }
    }
}
