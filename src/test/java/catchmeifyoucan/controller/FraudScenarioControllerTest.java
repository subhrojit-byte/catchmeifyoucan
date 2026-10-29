package catchmeifyoucan.controller;

import catchmeifyoucan.dto.FraudScenarioRequest;
import catchmeifyoucan.dto.FraudScenarioResponse;
import catchmeifyoucan.entity.Company;
import catchmeifyoucan.entity.FraudScenario;
import catchmeifyoucan.repository.CompanyRepository;
import catchmeifyoucan.service.FraudScenarioService;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;
import static org.springframework.test.web.servlet.setup.MockMvcBuilders.standaloneSetup;

import java.math.BigDecimal;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class FraudScenarioControllerTest {

    private final FraudScenarioService scenarioService = mock(FraudScenarioService.class);
    private final CompanyRepository companyRepository = mock(CompanyRepository.class);
    private final FraudScenarioController controller =
            new FraudScenarioController(scenarioService, companyRepository);

    @Test
    void validRequestResolvesBothCompaniesAndCreatesScenario() {
        Company source = company(1L);
        Company target = company(2L);
        FraudScenario scenario = new FraudScenario();
        scenario.setSourceCompany(source);
        scenario.setTargetCompany(target);
        scenario.setTargetAmount(new BigDecimal("10.00"));

        FraudScenarioRequest request = new FraudScenarioRequest();
        request.setSourceCompanyId(1L);
        request.setTargetCompanyId(2L);
        request.setAmount(new BigDecimal("10.00"));
        when(companyRepository.findById(1L)).thenReturn(Optional.of(source));
        when(companyRepository.findById(2L)).thenReturn(Optional.of(target));
        when(scenarioService.createScenario(source, target, request.getAmount()))
                .thenReturn(scenario);

        var response = controller.createScenario(request);

        assertEquals(200, response.getStatusCode().value());
        verify(scenarioService).createScenario(source, target, request.getAmount());
    }

    @Test
    void missingSourceIdIsRejectedBeforeRepositoryLookup() {
        FraudScenarioRequest request = new FraudScenarioRequest();
        request.setTargetCompanyId(2L);
        request.setAmount(new BigDecimal("10.00"));

        assertThrows(IllegalArgumentException.class,
                () -> controller.createScenario(request));
    }

    @Test
    void missingTargetIdAndNonPositiveAmountAreRejected() {
        FraudScenarioRequest missingTarget = new FraudScenarioRequest();
        missingTarget.setSourceCompanyId(1L);
        missingTarget.setAmount(new BigDecimal("10.00"));
        assertThrows(IllegalArgumentException.class,
                () -> controller.createScenario(missingTarget));

        FraudScenarioRequest invalidAmount = new FraudScenarioRequest();
        invalidAmount.setSourceCompanyId(1L);
        invalidAmount.setTargetCompanyId(2L);
        invalidAmount.setAmount(BigDecimal.ZERO);
        assertThrows(IllegalArgumentException.class,
                () -> controller.createScenario(invalidAmount));
    }

    @Test
    void emptyJsonReturnsBadRequestInsteadOfServerError() throws Exception {
        MockMvc mockMvc = standaloneSetup(controller)
                .setControllerAdvice(new ApiExceptionHandler())
                .build();

        mockMvc.perform(post("/api/fraud/scenarios")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{}"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.message")
                        .value("Source company ID is required."));
    }

    @Test
    void missingSourceCompanyReturnsItsSpecificBadRequestMessage() throws Exception {
        MockMvc mockMvc = standaloneSetup(controller)
                .setControllerAdvice(new ApiExceptionHandler())
                .build();
        when(companyRepository.findById(7271L)).thenReturn(Optional.empty());

        mockMvc.perform(post("/api/fraud/scenarios")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"sourceCompanyId":7271,"targetCompanyId":7272,"amount":10000000.00}
                                """))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.error").value("Invalid action"))
                .andExpect(jsonPath("$.message").value("Source company not found."));
    }

    private Company company(Long id) {
        Company company = new Company();
        try {
            var field = Company.class.getDeclaredField("id");
            field.setAccessible(true);
            field.set(company, id);
        } catch (ReflectiveOperationException exception) {
            throw new AssertionError(exception);
        }
        company.setCompanyName("Company " + id);
        company.setShellCompany(false);
        return company;
    }
}
