package catchmeifyoucan.dto;

import catchmeifyoucan.entity.FraudScenario;
import catchmeifyoucan.entity.FraudTurn;
import lombok.Getter;

import java.math.BigDecimal;
import java.util.List;

@Getter
public class FraudScenarioResponse {
    private final Long id;
    private final CompanyObservationResponse sourceCompany;
    private final CompanyObservationResponse targetCompany;
    private final BigDecimal targetAmount;
    private final List<FraudPositionResponse> positions;
    private final String status;
    private final int step;
    private final FraudTurn turn;
    private final int investigatorActionsRemaining;
    private final Boolean financialObjectiveAchieved;

    public FraudScenarioResponse(FraudScenario scenario) {
        this.id = scenario.getId();
        this.sourceCompany = new CompanyObservationResponse(scenario.getSourceCompany());
        this.targetCompany = new CompanyObservationResponse(scenario.getTargetCompany());
        this.targetAmount = scenario.getTargetAmount();
        this.positions = scenario.getPositions().stream()
                .map(FraudPositionResponse::new)
                .toList();
        this.status = scenario.getStatus();
        this.step = scenario.getStep();
        this.turn = scenario.getTurn();
        this.investigatorActionsRemaining = scenario.getInvestigatorActionsRemaining();
        this.financialObjectiveAchieved = scenario.getFinancialObjectiveAchieved();
    }
}
