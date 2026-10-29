package catchmeifyoucan.service;

import catchmeifyoucan.entity.CompanyDirector;
import catchmeifyoucan.entity.FraudScenario;
import catchmeifyoucan.entity.InvestigatorAction;
import catchmeifyoucan.entity.InvestigatorActionType;
import catchmeifyoucan.entity.Transaction;
import catchmeifyoucan.repository.CompanyDirectorRepository;
import catchmeifyoucan.repository.InvestigatorActionRepository;
import org.springframework.stereotype.Service;

import java.util.LinkedHashSet;
import java.util.Set;

/**
 * Resolves the companies that the investigator has legitimately encountered
 * in a scenario. The resolver uses persisted scenario state and successful
 * investigator actions, never client-supplied candidate IDs.
 */
@Service
public class InvestigatorCandidateService {

    private final InvestigatorActionRepository actionRepository;
    private final CompanyDirectorRepository companyDirectorRepository;

    public InvestigatorCandidateService(
            InvestigatorActionRepository actionRepository,
            CompanyDirectorRepository companyDirectorRepository) {
        this.actionRepository = actionRepository;
        this.companyDirectorRepository = companyDirectorRepository;
    }

    public Set<Long> resolveCompanyIds(FraudScenario scenario) {
        Set<Long> companyIds = new LinkedHashSet<>();
        add(companyIds, scenario.getSourceCompany());
        add(companyIds, scenario.getTargetCompany());
        scenario.getPositions().forEach(position -> add(companyIds, position.getCompany()));

        for (InvestigatorAction action : actionRepository.findByScenarioId(scenario.getId())) {
            if (action.getActionType() == InvestigatorActionType.OBSERVE_COMPANY
                    || action.getActionType() == InvestigatorActionType.INVESTIGATE_DIRECTORS) {
                add(companyIds, action.getTargetCompany());
                if (action.getActionType() == InvestigatorActionType.INVESTIGATE_DIRECTORS
                        && action.getTargetCompany() != null) {
                    companyDirectorRepository.findByCompanyId(action.getTargetCompany().getId())
                            .stream()
                            .map(CompanyDirector::getDirector)
                            .flatMap(director -> companyDirectorRepository
                                    .findByDirectorId(director.getId()).stream())
                            .forEach(relationship -> add(companyIds, relationship.getCompany()));
                }
            }

            if (action.getActionType() == InvestigatorActionType.TRACE_TRANSACTION) {
                Transaction transaction = action.getTransaction();
                if (transaction != null && transaction.getScenario() != null
                        && scenario.getId().equals(transaction.getScenario().getId())) {
                    add(companyIds, transaction.getSourceCompany());
                    add(companyIds, transaction.getDestinationCompany());
                }
            }
        }
        return companyIds;
    }

    private void add(Set<Long> companyIds, catchmeifyoucan.entity.Company company) {
        if (company != null && company.getId() != null) {
            companyIds.add(company.getId());
        }
    }
}
