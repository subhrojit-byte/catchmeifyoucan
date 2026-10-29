package catchmeifyoucan.service;

import org.springframework.stereotype.Service;

import java.util.UUID;

/** Performs a no-action shell-route readiness check under a temporary run-scoped grant. */
@Service
public class InvestigatorTrainingPreflightService {
    private final FraudsterRunCredentialService credentialService;
    private final FraudsterPrivateShellKnowledgeService shellKnowledgeService;

    public InvestigatorTrainingPreflightService(
            FraudsterRunCredentialService credentialService,
            FraudsterPrivateShellKnowledgeService shellKnowledgeService) {
        this.credentialService = credentialService;
        this.shellKnowledgeService = shellKnowledgeService;
    }

    public boolean hasLegalAuthorizedShellRoute(long scenarioId) {
        if (scenarioId <= 0) {
            return false;
        }
        String preflightRunId = UUID.randomUUID().toString();
        try {
            FraudsterRunCredentialService.IssuedCredential issued =
                    credentialService.issueForPreflight(scenarioId, preflightRunId);
            return credentialService.withAuthorization(
                    issued.token(), scenarioId, preflightRunId,
                    FraudsterRunCredentialService.ROLE,
                    FraudsterRunCredentialService.PREFLIGHT_OPERATION,
                    () -> shellKnowledgeService.hasLegalAuthorizedShellRoute(scenarioId)
            ).orElse(false);
        } finally {
            credentialService.revokeRun(preflightRunId);
        }
    }
}
