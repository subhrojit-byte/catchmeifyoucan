package catchmeifyoucan.repository;

import catchmeifyoucan.entity.InvestigatorAction;
import catchmeifyoucan.entity.InvestigatorActionType;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface InvestigatorActionRepository
        extends JpaRepository<InvestigatorAction, Long> {

    boolean existsByScenarioIdAndActionTypeAndTargetCompanyId(
            Long scenarioId, InvestigatorActionType actionType, Long targetCompanyId);

    List<InvestigatorAction> findByScenarioId(Long scenarioId);
}
