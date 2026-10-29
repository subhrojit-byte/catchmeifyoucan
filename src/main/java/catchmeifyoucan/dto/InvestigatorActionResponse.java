package catchmeifyoucan.dto;

import catchmeifyoucan.entity.InvestigatorAction;
import catchmeifyoucan.entity.FraudTurn;
import lombok.Getter;

@Getter
public class InvestigatorActionResponse {
    private final Long actionId;
    private final Long scenarioId;
    private final String actionType;
    private final int step;
    private final int currentStep;
    private final FraudTurn turn;
    private final int investigatorActionsRemaining;
    private final String status;
    private final Boolean financialObjectiveAchieved;
    private final Long companyId;
    private final Long transactionId;
    private final CompanyObservationResponse observation;
    private final DirectorInvestigationResponse directorInvestigation;
    private final TransactionTraceResponse transactionTrace;

    public InvestigatorActionResponse(InvestigatorAction action,
                                      CompanyObservationResponse observation,
                                      DirectorInvestigationResponse directorInvestigation,
                                      TransactionTraceResponse transactionTrace) {
        this.actionId = action.getId();
        this.scenarioId = action.getScenario().getId();
        this.actionType = action.getActionType().name();
        this.step = action.getStep();
        this.currentStep = action.getScenario().getStep();
        this.turn = action.getScenario().getTurn();
        this.investigatorActionsRemaining = action.getScenario().getInvestigatorActionsRemaining();
        this.status = action.getScenario().getStatus();
        this.financialObjectiveAchieved = action.getScenario().getFinancialObjectiveAchieved();
        this.companyId = action.getTargetCompany() == null ? null : action.getTargetCompany().getId();
        this.transactionId = action.getTransaction() == null ? null : action.getTransaction().getId();
        this.observation = observation;
        this.directorInvestigation = directorInvestigation;
        this.transactionTrace = transactionTrace;
    }
}
