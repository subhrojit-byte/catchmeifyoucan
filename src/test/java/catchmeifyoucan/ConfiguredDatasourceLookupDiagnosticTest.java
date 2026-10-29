package catchmeifyoucan;

import catchmeifyoucan.controller.ApiExceptionHandler;
import catchmeifyoucan.controller.FraudScenarioController;
import catchmeifyoucan.repository.CompanyRepository;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import static org.springframework.test.web.servlet.setup.MockMvcBuilders.standaloneSetup;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest(properties = "simulation.initialize=false")
class ConfiguredDatasourceLookupDiagnosticTest {
    @Autowired CompanyRepository companies;
    @Autowired FraudScenarioController controller;

    @Test
    void requestedScenarioCompaniesAreAbsentFromConfiguredDatasource() {
        boolean sourceFound = companies.findById(7271L).isPresent();
        boolean targetFound = companies.findById(7272L).isPresent();
        assertFalse(sourceFound,
                "source 7271 unexpectedly exists in the application's configured datasource");
        assertFalse(targetFound,
                "target 7272 unexpectedly exists in the application's configured datasource");
    }

    @Test
    void scenarioRequestReportsMissingSourceFromConfiguredDatasource() throws Exception {
        MockMvc mockMvc = standaloneSetup(controller)
                .setControllerAdvice(new ApiExceptionHandler())
                .build();

        mockMvc.perform(post("/api/fraud/scenarios")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"sourceCompanyId\":7271,\"targetCompanyId\":7272,\"amount\":10000000.00}"))
                .andExpect(status().isBadRequest())
                .andExpect(content().json("{\"error\":\"Invalid action\",\"message\":\"Source company not found.\"}"));
    }
}
