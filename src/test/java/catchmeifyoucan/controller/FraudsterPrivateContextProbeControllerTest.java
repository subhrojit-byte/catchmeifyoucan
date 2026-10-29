package catchmeifyoucan.controller;

import catchmeifyoucan.service.FraudsterRunCredentialService;
import catchmeifyoucan.service.FraudsterPrivateShellKnowledgeService;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;


import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;

class FraudsterPrivateContextProbeControllerTest {
    @Test
    void scenarioIdWithoutCredentialCannotCallProtectedOperation() {
        var service = new FraudsterRunCredentialService();
        var knowledge = mock(FraudsterPrivateShellKnowledgeService.class);
        var controller = new FraudsterPrivateContextProbeController(service, knowledge);

        var response = controller.authorizationProbe(7L, null, null);

        assertEquals(401, response.getStatusCode().value());
        assertFalse(response.getBody().containsKey("status"));
        org.mockito.Mockito.verifyNoInteractions(knowledge);
    }

    @Test
    void authorizedProbeReturnsOnlyPrivateIdsResolvedForItsScenario() {
        var service = new FraudsterRunCredentialService();
        var knowledge = mock(FraudsterPrivateShellKnowledgeService.class);
        when(knowledge.authorizedShellCompanyIds(7L)).thenReturn(List.of(21L, 35L));
        String credential = service.issue(7L, "run-7");
        var controller = new FraudsterPrivateContextProbeController(service, knowledge);

        var response = controller.authorizationProbe(7L, credential, "run-7");

        assertEquals(200, response.getStatusCode().value());
        assertEquals(java.util.Map.of(
                "status", "authorized", "privateShellCompanyIds", List.of(21L, 35L)),
                response.getBody());
    }
}
