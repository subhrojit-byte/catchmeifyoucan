package catchmeifyoucan.service;

import catchmeifyoucan.dto.FraudScenarioResponse;
import catchmeifyoucan.entity.Company;
import catchmeifyoucan.entity.FraudPosition;
import catchmeifyoucan.entity.FraudScenario;
import catchmeifyoucan.entity.FraudTurn;
import catchmeifyoucan.repository.FraudScenarioRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.util.Optional;

@Service
public class FraudScenarioService {

    private final FraudScenarioRepository fraudScenarioRepository;

    public FraudScenarioService(
            FraudScenarioRepository fraudScenarioRepository) {

        this.fraudScenarioRepository =
                fraudScenarioRepository;
    }

    public FraudScenario createScenario(
            Company sourceCompany,
            Company targetCompany,
            BigDecimal targetAmount) {

        // Validate companies
        if (sourceCompany == null
                || targetCompany == null) {

            throw new IllegalArgumentException(
                    "Source and target companies are required."
            );
        }

        // Source and target cannot be the same
        if (sourceCompany.equals(targetCompany)) {

            throw new IllegalArgumentException(
                    "Source and target companies must be different."
            );
        }

        // Validate amount
        if (targetAmount == null
                || targetAmount.compareTo(BigDecimal.ZERO) <= 0) {

            throw new IllegalArgumentException(
                    "Target amount must be greater than zero."
            );
        }

        // Create fraud scenario
        FraudScenario scenario =
                new FraudScenario();

        scenario.setSourceCompany(
                sourceCompany
        );

        scenario.setTargetCompany(
                targetCompany
        );

        scenario.setTargetAmount(
                targetAmount
        );

        scenario.setStatus(
                "ACTIVE"
        );

        scenario.setStep(0);
        scenario.setTurn(FraudTurn.FRAUDSTER);
        scenario.setInvestigatorActionsRemaining(0);
        scenario.setFinancialObjectiveAchieved(false);

        // Create the initial money position.
        // At the beginning of the fraud,
        // the entire amount is at the source company.
        FraudPosition initialPosition =
                new FraudPosition();

        initialPosition.setScenario(
                scenario
        );

        initialPosition.setCompany(
                sourceCompany
        );

        initialPosition.setAmount(
                targetAmount
        );

        scenario.getPositions().add(
                initialPosition
        );

        return fraudScenarioRepository.save(
                scenario
        );
    }

    @Transactional(readOnly = true)
    public Optional<FraudScenarioResponse> findScenario(Long scenarioId) {
        if (scenarioId == null) {
            return Optional.empty();
        }
        return fraudScenarioRepository.findById(scenarioId)
                .map(FraudScenarioResponse::new);
    }
}

