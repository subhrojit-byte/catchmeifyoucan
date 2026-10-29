package catchmeifyoucan.controller;

import catchmeifyoucan.service.InvestigatorTrainingPreflightService;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class InvestigatorTrainingPreflightControllerTest {
    @Test
    void returnsOnlyGenericReadiness() {
        InvestigatorTrainingPreflightService service = mock(InvestigatorTrainingPreflightService.class);
        when(service.hasLegalAuthorizedShellRoute(342L)).thenReturn(true);

        var response = new InvestigatorTrainingPreflightController(service).preflight(342L);

        assertEquals(HttpStatus.OK, response.getStatusCode());
        assertEquals(java.util.Map.of("ready", true), response.getBody());
    }

    @Test
    void hidesReadinessCheckFailuresBehindGenericNotReadyResponse() {
        InvestigatorTrainingPreflightService service = mock(InvestigatorTrainingPreflightService.class);
        when(service.hasLegalAuthorizedShellRoute(342L))
                .thenThrow(new IllegalStateException("private details must not escape"));

        var response = new InvestigatorTrainingPreflightController(service).preflight(342L);

        assertEquals(HttpStatus.SERVICE_UNAVAILABLE, response.getStatusCode());
        assertEquals(java.util.Map.of("ready", false), response.getBody());
        org.mockito.Mockito.verify(service).hasLegalAuthorizedShellRoute(342L);
    }
}
