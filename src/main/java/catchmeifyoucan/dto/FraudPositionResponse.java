package catchmeifyoucan.dto;

import catchmeifyoucan.entity.FraudPosition;
import lombok.Getter;

import java.math.BigDecimal;

@Getter
public class FraudPositionResponse {
    private final Long id;
    private final CompanyObservationResponse company;
    private final BigDecimal amount;

    public FraudPositionResponse(FraudPosition position) {
        this.id = position.getId();
        this.company = new CompanyObservationResponse(position.getCompany());
        this.amount = position.getAmount();
    }
}
