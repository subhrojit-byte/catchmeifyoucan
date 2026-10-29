package catchmeifyoucan.controller;

import catchmeifyoucan.dto.FraudScenarioRequest;
import catchmeifyoucan.dto.FraudScenarioResponse;
import catchmeifyoucan.entity.Company;
import catchmeifyoucan.entity.FraudScenario;
import catchmeifyoucan.repository.CompanyRepository;
import catchmeifyoucan.service.FraudScenarioService;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.math.BigDecimal;

@RestController
@RequestMapping("/api/fraud/scenarios")
public class FraudScenarioController {

    private final FraudScenarioService fraudScenarioService;
    private final CompanyRepository companyRepository;

    public FraudScenarioController(
            FraudScenarioService fraudScenarioService,
            CompanyRepository companyRepository) {

        this.fraudScenarioService =
                fraudScenarioService;

        this.companyRepository =
                companyRepository;
    }

    @PostMapping
    public ResponseEntity<FraudScenarioResponse> createScenario(
            @RequestBody FraudScenarioRequest request) {

        validateRequest(request);

        Company sourceCompany =
                companyRepository
                        .findById(
                                request.getSourceCompanyId()
                        )
                        .orElseThrow(() ->
                                new IllegalArgumentException(
                                        "Source company not found."
                                )
                        );

        Company targetCompany =
                companyRepository
                        .findById(
                                request.getTargetCompanyId()
                        )
                        .orElseThrow(() ->
                                new IllegalArgumentException(
                                        "Target company not found."
                                )
                        );

        FraudScenario scenario =
                fraudScenarioService.createScenario(
                        sourceCompany,
                        targetCompany,
                        request.getAmount()
                );

        return ResponseEntity.ok(new FraudScenarioResponse(scenario));
    }

    private void validateRequest(FraudScenarioRequest request) {
        if (request == null) {
            throw new IllegalArgumentException("Scenario request body is required.");
        }
        if (request.getSourceCompanyId() == null) {
            throw new IllegalArgumentException("Source company ID is required.");
        }
        if (request.getTargetCompanyId() == null) {
            throw new IllegalArgumentException("Target company ID is required.");
        }
        if (request.getAmount() == null
                || request.getAmount().compareTo(BigDecimal.ZERO) <= 0) {
            throw new IllegalArgumentException("Target amount must be greater than zero.");
        }
    }

    @GetMapping("/{scenarioId}")
    public ResponseEntity<FraudScenarioResponse> getScenario(
            @PathVariable Long scenarioId) {

        return fraudScenarioService.findScenario(scenarioId)
                .map(ResponseEntity::ok)
                .orElseGet(() -> ResponseEntity.notFound().build());
    }
}
