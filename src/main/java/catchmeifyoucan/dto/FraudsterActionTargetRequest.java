package catchmeifyoucan.dto;

import lombok.Getter;
import lombok.Setter;

import java.math.BigDecimal;

@Getter
public class FraudsterActionTargetRequest {

    @Setter
    private Long destinationCompanyId;

    @Setter
    private BigDecimal amount;

    public FraudsterActionTargetRequest() {
    }
}
