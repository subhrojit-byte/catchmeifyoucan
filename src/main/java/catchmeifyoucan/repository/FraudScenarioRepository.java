package catchmeifyoucan.repository;

import catchmeifyoucan.entity.FraudScenario;
import org.springframework.data.jpa.repository.JpaRepository;

public interface FraudScenarioRepository
        extends JpaRepository<FraudScenario, Long> {
}