package catchmeifyoucan.controller;

import catchmeifyoucan.entity.CompanyDirector;
import catchmeifyoucan.dto.CompanyDirectorResponse;
import catchmeifyoucan.service.CompanyDirectorService;
import catchmeifyoucan.service.CompanyRelationshipService;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/api/company-directors")
public class CompanyDirectorController {

    private final CompanyDirectorService companyDirectorService;
    private final CompanyRelationshipService companyRelationshipService;

    public CompanyDirectorController(
            CompanyDirectorService companyDirectorService,
            CompanyRelationshipService companyRelationshipService) {

        this.companyDirectorService = companyDirectorService;
        this.companyRelationshipService = companyRelationshipService;
    }

    @PostMapping("/{companyId}/{directorId}")
    public CompanyDirectorResponse assignDirector(
            @PathVariable Long companyId,
            @PathVariable Long directorId) {

        return new CompanyDirectorResponse(companyDirectorService.assignDirector(
                companyId,
                directorId
        ));
    }

    @GetMapping("/company/{companyId}")
    public List<CompanyDirectorResponse> getDirectorsForCompany(
            @PathVariable Long companyId) {

        return companyDirectorService
                .getDirectorsForCompany(companyId).stream()
                .map(CompanyDirectorResponse::new)
                .toList();
    }

    @GetMapping("/director/{directorId}")
    public List<CompanyDirectorResponse> getCompaniesForDirector(
            @PathVariable Long directorId) {

        return companyDirectorService
                .getCompaniesForDirector(directorId).stream()
                .map(CompanyDirectorResponse::new)
                .toList();
    }

    @GetMapping("/eligible/{companyId}")
    public List<Long> getEligibleIntermediateCompanies(@PathVariable Long companyId) {
        return companyRelationshipService.eligibleIntermediateCompanyIds(companyId, null)
                .stream().toList();
    }
}
