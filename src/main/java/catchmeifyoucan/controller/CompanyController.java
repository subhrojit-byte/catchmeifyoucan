package catchmeifyoucan.controller;

import catchmeifyoucan.entity.Company;
import catchmeifyoucan.dto.CompanyObservationResponse;
import catchmeifyoucan.dto.CompanyDirectoryStatusResponse;
import catchmeifyoucan.service.CompanyService;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.net.InetAddress;
import java.net.UnknownHostException;
import java.util.List;

@RestController
@RequestMapping("/api/companies")
public class CompanyController {

    private final CompanyService companyService;

    public CompanyController(CompanyService companyService) {
        this.companyService = companyService;
    }

    @PostMapping
    public CompanyObservationResponse createCompany(@RequestBody Company company) {
        return new CompanyObservationResponse(companyService.createCompany(company));
    }

    @GetMapping
    public List<CompanyObservationResponse> getAllCompanies() {
        return companyService.getAllCompanies().stream()
                .map(CompanyObservationResponse::new)
                .toList();
    }

    /**
     * Local college-demo ground truth for the human directory only.
     * This is not an authenticated analyst API; do not expose through a proxy
     * or deploy on an untrusted network. Investigator clients use the public
     * observation DTO endpoints above and do not call this route.
     */
    @GetMapping("/directory")
    public ResponseEntity<List<CompanyDirectoryStatusResponse>> getDirectoryStatuses(
            HttpServletRequest request) {
        if (!isLoopback(request.getRemoteAddr())) {
            return ResponseEntity.status(HttpStatus.FORBIDDEN).build();
        }
        List<CompanyDirectoryStatusResponse> statuses = companyService.getAllCompanies().stream()
                .map(CompanyDirectoryStatusResponse::new)
                .toList();
        return ResponseEntity.ok(statuses);
    }

    @GetMapping("/{id}")
    public CompanyObservationResponse getCompany(@PathVariable Long id) {
        Company company = companyService.getCompany(id);
        return company == null ? null : new CompanyObservationResponse(company);
    }

    private boolean isLoopback(String remoteAddress) {
        try {
            return remoteAddress != null && InetAddress.getByName(remoteAddress).isLoopbackAddress();
        } catch (UnknownHostException ignored) {
            return false;
        }
    }
}
