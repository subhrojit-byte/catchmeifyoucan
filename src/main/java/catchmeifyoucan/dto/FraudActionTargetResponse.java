package catchmeifyoucan.dto;

import catchmeifyoucan.entity.FraudActionTarget;
import lombok.Getter;

import java.math.BigDecimal;

@Getter
public class FraudActionTargetResponse {
    private final Long id;
    private final Long destinationCompanyId;
    private final BigDecimal amount;

    public FraudActionTargetResponse(FraudActionTarget target) {
        this.id = target.getId();
        this.destinationCompanyId = target.getDestinationCompany() == null
                ? null : target.getDestinationCompany().getId();
        this.amount = target.getAmount();
    }
}
