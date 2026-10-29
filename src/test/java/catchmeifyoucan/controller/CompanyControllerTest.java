package catchmeifyoucan.controller;

import catchmeifyoucan.entity.Company;
import catchmeifyoucan.service.CompanyService;
import jakarta.servlet.http.HttpServletRequest;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.when;

class CompanyControllerTest {
    @Test
    void directoryStatusIsAvailableToLoopbackClientsOnly() {
        CompanyService service = mock(CompanyService.class);
        Company shell = new Company();
        shell.setShellCompany(true);
        Company legitimate = new Company();
        legitimate.setShellCompany(false);
        when(service.getAllCompanies()).thenReturn(List.of(shell, legitimate));
        HttpServletRequest request = mock(HttpServletRequest.class);
        when(request.getRemoteAddr()).thenReturn("127.0.0.1");

        var response = new CompanyController(service).getDirectoryStatuses(request);

        assertEquals(HttpStatus.OK, response.getStatusCode());
        assertEquals(List.of(true, false), response.getBody().stream()
                .map(status -> status.shellCompany()).toList());
    }

    @Test
    void directoryStatusRejectsNonLoopbackClientsWithoutReadingCompanies() {
        CompanyService service = mock(CompanyService.class);
        HttpServletRequest request = mock(HttpServletRequest.class);
        when(request.getRemoteAddr()).thenReturn("192.0.2.10");

        var response = new CompanyController(service).getDirectoryStatuses(request);

        assertEquals(HttpStatus.FORBIDDEN, response.getStatusCode());
        assertFalse(response.hasBody());
        verify(service, never()).getAllCompanies();
    }
}
