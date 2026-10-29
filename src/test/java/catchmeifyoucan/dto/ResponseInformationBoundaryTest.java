package catchmeifyoucan.dto;

import catchmeifyoucan.entity.Company;
import catchmeifyoucan.entity.CompanyDirector;
import catchmeifyoucan.entity.Director;
import tools.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class ResponseInformationBoundaryTest {

    private final ObjectMapper objectMapper = new ObjectMapper();

    @Test
    void companyAndRelationshipResponsesExcludeShellCompany() throws Exception {
        Company company = new Company();
        company.setCompanyName("Boundary Company");
        company.setShellCompany(true);
        Director director = new Director("Boundary Director");

        String companyJson = objectMapper.writeValueAsString(
                new CompanyObservationResponse(company));
        String directoryJson = objectMapper.writeValueAsString(
                new CompanyDirectoryStatusResponse(company));
        String relationshipJson = objectMapper.writeValueAsString(
                new CompanyDirectorResponse(new CompanyDirector(company, director)));

        assertFalse(companyJson.contains("shellCompany"));
        assertFalse(relationshipJson.contains("shellCompany"));
        assertTrue(directoryJson.contains("\"shellCompany\":true"));
    }
}
