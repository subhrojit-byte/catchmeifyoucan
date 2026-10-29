package catchmeifyoucan.repository;

import catchmeifyoucan.entity.Director;
import org.springframework.data.jpa.repository.JpaRepository;

public interface DirectorRepository extends JpaRepository<Director, Long> {
}