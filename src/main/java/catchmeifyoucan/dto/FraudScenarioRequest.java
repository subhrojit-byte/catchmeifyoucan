package catchmeifyoucan.dto;

import lombok.Getter;
import lombok.Setter;

import java.math.BigDecimal;

@Getter
public class FraudScenarioRequest {

    @Setter
    private Long sourceCompanyId;
    @Setter
    private Long targetCompanyId;
    @Setter
    private BigDecimal amount;

    public FraudScenarioRequest() {
    }


}