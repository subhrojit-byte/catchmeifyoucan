package catchmeifyoucan.controller;

import catchmeifyoucan.service.FraudsterRunCredentialService;
import catchmeifyoucan.service.FraudsterPrivateShellKnowledgeService;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/** Harmless protected-operation probe; private scenario data is not implemented here. */
@RestController
@RequestMapping("/api/fraudster-private")
public class FraudsterPrivateContextProbeController {
    private final FraudsterRunCredentialService credentialService;
    private final FraudsterPrivateShellKnowledgeService shellKnowledgeService;

    public FraudsterPrivateContextProbeController(
            FraudsterRunCredentialService credentialService,
            FraudsterPrivateShellKnowledgeService shellKnowledgeService) {
        this.credentialService = credentialService;
        this.shellKnowledgeService = shellKnowledgeService;
    }

    @GetMapping("/{scenarioId}/authorization-probe")
    public ResponseEntity<Map<String, Object>> authorizationProbe(
            @PathVariable long scenarioId,
            @RequestHeader(value = FraudsterRunCredentialService.HEADER, required = false) String credential,
            @RequestHeader(value = FraudsterRunCredentialService.RUN_ID_HEADER, required = false) String runId) {
        return credentialService.withAuthorization(
                        credential,
                        scenarioId,
                        runId,
                        FraudsterRunCredentialService.ROLE,
                        FraudsterRunCredentialService.OPERATION,
                        () -> ResponseEntity.ok(Map.of(
                                "status", "authorized",
                                "privateShellCompanyIds",
                                shellKnowledgeService.authorizedShellCompanyIds(scenarioId))))
                .orElseGet(() -> ResponseEntity.status(HttpStatus.UNAUTHORIZED)
                        .body(Map.of("message", "Unauthorized.")));
    }
}
