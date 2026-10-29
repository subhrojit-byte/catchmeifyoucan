package catchmeifyoucan.service;

import catchmeifyoucan.entity.CompanyDirector;
import catchmeifyoucan.repository.CompanyDirectorRepository;
import org.springframework.stereotype.Service;

import java.util.HashSet;
import java.util.Set;

@Service
public class CompanyRelationshipService {

    private final CompanyDirectorRepository companyDirectorRepository;

    public CompanyRelationshipService(CompanyDirectorRepository companyDirectorRepository) {
        this.companyDirectorRepository = companyDirectorRepository;
    }

    public Set<Long> eligibleIntermediateCompanyIds(Long sourceCompanyId, Long targetCompanyId) {
        Set<Long> sourceDirectorIds = new HashSet<>();
        for (CompanyDirector relationship : companyDirectorRepository.findByCompanyId(sourceCompanyId)) {
            if (relationship.getDirector() != null && relationship.getDirector().getId() != null) {
                sourceDirectorIds.add(relationship.getDirector().getId());
            }
        }

        Set<Long> eligibleCompanyIds = new HashSet<>();
        for (Long directorId : sourceDirectorIds) {
            for (CompanyDirector relationship : companyDirectorRepository.findByDirectorId(directorId)) {
                if (relationship.getCompany() != null && relationship.getCompany().getId() != null
                        && !relationship.getCompany().getId().equals(sourceCompanyId)
                        && !relationship.getCompany().getId().equals(targetCompanyId)) {
                    eligibleCompanyIds.add(relationship.getCompany().getId());
                }
            }
        }
        return eligibleCompanyIds;
    }
}
