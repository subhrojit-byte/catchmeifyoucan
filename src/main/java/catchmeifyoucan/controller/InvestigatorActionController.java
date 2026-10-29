package catchmeifyoucan.controller;

import catchmeifyoucan.dto.InvestigatorActionRequest;
import catchmeifyoucan.dto.InvestigatorActionResponse;
import catchmeifyoucan.service.InvestigatorActionService;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/investigator/actions")
public class InvestigatorActionController {

    private final InvestigatorActionService investigatorActionService;

    public InvestigatorActionController(InvestigatorActionService investigatorActionService) {
        this.investigatorActionService = investigatorActionService;
    }

    @PostMapping
    public ResponseEntity<InvestigatorActionResponse> submitAction(
            @RequestBody InvestigatorActionRequest request) {
        return ResponseEntity.ok(investigatorActionService.submitAction(request));
    }
}
