package catchmeifyoucan.dto;

import catchmeifyoucan.entity.FraudActionType;
import lombok.Getter;
import lombok.Setter;

import java.util.List;

@Getter
public class FraudsterActionRequest {

    @Setter
    private Long scenarioId;

    @Setter
    private FraudActionType actionType;

    @Setter
    private Long sourcePositionId;

    @Setter
    private List<FraudsterActionTargetRequest> targets;

    public FraudsterActionRequest() {
    }
}
