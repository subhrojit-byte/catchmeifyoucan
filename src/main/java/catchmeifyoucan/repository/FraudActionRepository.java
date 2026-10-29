package catchmeifyoucan.repository;

import catchmeifyoucan.entity.FraudAction;
import org.springframework.data.jpa.repository.JpaRepository;

public interface FraudActionRepository extends JpaRepository<FraudAction, Long> {
}
