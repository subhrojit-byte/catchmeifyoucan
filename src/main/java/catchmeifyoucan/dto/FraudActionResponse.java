package catchmeifyoucan.dto;

import catchmeifyoucan.entity.FraudAction;
import lombok.Getter;

import java.util.List;

@Getter
public class FraudActionResponse {
    private final Long id;
    private final String actionType;
    private final Long sourcePositionId;
    private final int step;
    private final List<FraudActionTargetResponse> targets;

    public FraudActionResponse(FraudAction action) {
        this.id = action.getId();
        this.actionType = action.getActionType().name();
        this.sourcePositionId = action.getSourcePosition() == null
                ? null : action.getSourcePosition().getId();
        this.step = action.getStep();
        this.targets = action.getTargets().stream()
                .map(FraudActionTargetResponse::new)
                .toList();
    }
}
