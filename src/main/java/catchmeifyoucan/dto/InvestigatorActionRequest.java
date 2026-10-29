package catchmeifyoucan.dto;

import catchmeifyoucan.entity.InvestigatorActionType;
import lombok.Getter;
import lombok.Setter;

@Getter
public class InvestigatorActionRequest {

    @Setter
    private Long scenarioId;

    @Setter
    private InvestigatorActionType actionType;

    @Setter
    private Long companyId;

    @Setter
    private Long transactionId;

    public InvestigatorActionRequest() {
    }
}
