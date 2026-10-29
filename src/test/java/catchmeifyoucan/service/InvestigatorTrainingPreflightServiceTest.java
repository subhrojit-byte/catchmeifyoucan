package catchmeifyoucan.service;

import catchmeifyoucan.controller.InvestigatorTrainingPreflightController;
import catchmeifyoucan.repository.CompanyRepository;
import catchmeifyoucan.repository.FraudScenarioRepository;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.lang.reflect.Modifier;
import java.util.Arrays;
import java.util.Set;
import java.util.stream.Collectors;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class InvestigatorTrainingPreflightServiceTest {
    @Test
    void returnsReadinessAndRevokesTheEphemeralGrantOnSuccess() {
        CapturingCredentialService credentials = new CapturingCredentialService();
        FraudsterPrivateShellKnowledgeService knowledge = mock(FraudsterPrivateShellKnowledgeService.class);
        when(knowledge.hasLegalAuthorizedShellRoute(342L)).thenReturn(true);
        InvestigatorTrainingPreflightService service =
                new InvestigatorTrainingPreflightService(credentials, knowledge);

        assertTrue(service.hasLegalAuthorizedShellRoute(342L));

        assertTrue(credentials.preflightRunId != null && !credentials.preflightRunId.isBlank());
        assertFalse(credentials.authorizes(credentials.token, 342L, credentials.preflightRunId,
                FraudsterRunCredentialService.ROLE, FraudsterRunCredentialService.PREFLIGHT_OPERATION));
        verify(knowledge).hasLegalAuthorizedShellRoute(342L);
        org.mockito.Mockito.verifyNoMoreInteractions(knowledge);
    }

    @Test
    void revokesTheEphemeralGrantWhenTheReadOnlyCheckThrows() {
        CapturingCredentialService credentials = new CapturingCredentialService();
        FraudsterPrivateShellKnowledgeService knowledge = mock(FraudsterPrivateShellKnowledgeService.class);
        when(knowledge.hasLegalAuthorizedShellRoute(342L))
                .thenThrow(new IllegalStateException("read-only lookup failed"));
        InvestigatorTrainingPreflightService service =
                new InvestigatorTrainingPreflightService(credentials, knowledge);

        assertThrows(IllegalStateException.class, () -> service.hasLegalAuthorizedShellRoute(342L));

        assertFalse(credentials.authorizes(credentials.token, 342L, credentials.preflightRunId,
                FraudsterRunCredentialService.ROLE, FraudsterRunCredentialService.PREFLIGHT_OPERATION));
        verify(knowledge).hasLegalAuthorizedShellRoute(342L);
        org.mockito.Mockito.verifyNoMoreInteractions(knowledge);
    }

    @Test
    void nonpositiveScenarioDoesNotIssueGrantOrReadScenarioData() {
        CapturingCredentialService credentials = new CapturingCredentialService();
        FraudsterPrivateShellKnowledgeService knowledge = mock(FraudsterPrivateShellKnowledgeService.class);
        InvestigatorTrainingPreflightService service =
                new InvestigatorTrainingPreflightService(credentials, knowledge);

        assertFalse(service.hasLegalAuthorizedShellRoute(0));

        assertTrue(credentials.preflightRunId == null);
        org.mockito.Mockito.verifyNoInteractions(knowledge);
    }

    @Test
    void preflightDependencyBoundaryExcludesScenarioActionTransactionAndCheckpointMutators() {
        assertEquals(Set.of(FraudsterRunCredentialService.class, FraudsterPrivateShellKnowledgeService.class),
                dependencyTypes(InvestigatorTrainingPreflightService.class));
        assertEquals(Set.of(FraudScenarioRepository.class, CompanyRepository.class,
                        CompanyRelationshipService.class),
                dependencyTypes(FraudsterPrivateShellKnowledgeService.class));
        assertEquals(Set.of(InvestigatorTrainingPreflightService.class),
                dependencyTypes(InvestigatorTrainingPreflightController.class));
    }

    private static Set<Class<?>> dependencyTypes(Class<?> type) {
        return Arrays.stream(type.getDeclaredFields())
                .filter(field -> !Modifier.isStatic(field.getModifiers()))
                .map(Field::getType)
                .collect(Collectors.toSet());
    }

    private static final class CapturingCredentialService extends FraudsterRunCredentialService {
        private String token;
        private String preflightRunId;

        @Override
        IssuedCredential issueForPreflight(long scenarioId, String runId) {
            IssuedCredential issued = super.issueForPreflight(scenarioId, runId);
            this.token = issued.token();
            this.preflightRunId = runId;
            return issued;
        }
    }
}
