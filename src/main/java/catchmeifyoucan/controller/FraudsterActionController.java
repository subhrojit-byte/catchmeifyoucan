package catchmeifyoucan.controller;

import catchmeifyoucan.dto.FraudsterActionRequest;
import catchmeifyoucan.dto.FraudActionResponse;
import catchmeifyoucan.dto.FraudScenarioResponse;
import catchmeifyoucan.service.FraudsterActionService;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/fraud/actions")
public class FraudsterActionController {

    private final FraudsterActionService fraudsterActionService;

    public FraudsterActionController(
            FraudsterActionService fraudsterActionService) {

        this.fraudsterActionService = fraudsterActionService;
    }

    @PostMapping
    public ResponseEntity<FraudActionResponse> createAction(
            @RequestBody FraudsterActionRequest request) {

        return ResponseEntity.ok(new FraudActionResponse(
                fraudsterActionService.createAction(request)));
    }

    @PostMapping("/{actionId}/execute")
    public ResponseEntity<FraudScenarioResponse> executeAction(
            @PathVariable Long actionId) {

        return ResponseEntity.ok(new FraudScenarioResponse(
                fraudsterActionService.executeAction(actionId)));
    }
}
