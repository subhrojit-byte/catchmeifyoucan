package catchmeifyoucan.repository;

import catchmeifyoucan.entity.CompanyDirector;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface CompanyDirectorRepository extends JpaRepository<CompanyDirector, Long> {

    List<CompanyDirector> findByCompanyId(Long companyId);

    List<CompanyDirector> findByDirectorId(Long directorId);
}