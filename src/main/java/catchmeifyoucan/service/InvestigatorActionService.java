package catchmeifyoucan.service;

import catchmeifyoucan.dto.CompanyObservationResponse;
import catchmeifyoucan.dto.DirectorInvestigationResponse;
import catchmeifyoucan.dto.DirectorRelationshipResponse;
import catchmeifyoucan.dto.InvestigatorActionRequest;
import catchmeifyoucan.dto.InvestigatorActionResponse;
import catchmeifyoucan.dto.TransactionTraceResponse;
import catchmeifyoucan.entity.Company;
import catchmeifyoucan.entity.CompanyDirector;
import catchmeifyoucan.entity.FraudScenario;
import catchmeifyoucan.entity.InvestigatorAction;
import catchmeifyoucan.entity.InvestigatorActionType;
import catchmeifyoucan.entity.FraudTurn;
import catchmeifyoucan.entity.Transaction;
import catchmeifyoucan.repository.CompanyDirectorRepository;
import catchmeifyoucan.repository.CompanyRepository;
import catchmeifyoucan.repository.FraudScenarioRepository;
import catchmeifyoucan.repository.InvestigatorActionRepository;
import catchmeifyoucan.repository.TransactionRepository;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

@Service
public class InvestigatorActionService {

    /** Maximum fraudster turns; exhaustion is distinct from objective success. */
    @Value("${simulation.fraud.max-turns:10}")
    private int maxFraudsterTurns = 10;

    private final FraudScenarioRepository scenarioRepository;
    private final InvestigatorActionRepository actionRepository;
    private final CompanyRepository companyRepository;
    private final TransactionRepository transactionRepository;
    private final CompanyDirectorRepository companyDirectorRepository;
    private final InvestigatorCandidateService candidateService;

    @Autowired
    public InvestigatorActionService(
            FraudScenarioRepository scenarioRepository,
            InvestigatorActionRepository actionRepository,
            CompanyRepository companyRepository,
            TransactionRepository transactionRepository,
            CompanyDirectorRepository companyDirectorRepository,
            InvestigatorCandidateService candidateService) {
        this.scenarioRepository = scenarioRepository;
        this.actionRepository = actionRepository;
        this.companyRepository = companyRepository;
        this.transactionRepository = transactionRepository;
        this.companyDirectorRepository = companyDirectorRepository;
        this.candidateService = candidateService;
    }

    /** Compatibility constructor for focused unit tests and existing callers. */
    public InvestigatorActionService(
            FraudScenarioRepository scenarioRepository,
            InvestigatorActionRepository actionRepository,
            CompanyRepository companyRepository,
            TransactionRepository transactionRepository,
            CompanyDirectorRepository companyDirectorRepository) {
        this(scenarioRepository, actionRepository, companyRepository,
                transactionRepository, companyDirectorRepository,
                new InvestigatorCandidateService(actionRepository, companyDirectorRepository));
    }

    @Transactional
    public InvestigatorActionResponse submitAction(InvestigatorActionRequest request) {
        if (request == null || request.getScenarioId() == null) {
            throw new IllegalArgumentException("Scenario is required.");
        }
        FraudScenario scenario = scenarioRepository.findById(request.getScenarioId())
                .orElseThrow(() -> new IllegalArgumentException("Scenario not found."));
        if (!"ACTIVE".equals(scenario.getStatus())) {
            throw new IllegalArgumentException("Scenario is not ACTIVE.");
        }
        if (scenario.getTurn() != FraudTurn.INVESTIGATOR) {
            throw new IllegalArgumentException("It is not the investigator turn.");
        }
        if (scenario.getInvestigatorActionsRemaining() <= 0) {
            throw new IllegalArgumentException("No investigator actions remaining.");
        }
        if (request.getActionType() == null) {
            throw new IllegalArgumentException("Action type is required.");
        }

        InvestigatorActionType type = request.getActionType();
        Company company = null;
        Transaction transaction = null;
        if (requiresCompany(type)) {
            if (request.getCompanyId() == null) {
                throw new IllegalArgumentException("Company is required for this action.");
            }
            company = companyRepository.findById(request.getCompanyId())
                    .orElseThrow(() -> new IllegalArgumentException("Company not found."));
        }
        Boolean flagCorrect = null;
        if (type == InvestigatorActionType.FLAG_COMPANY) {
            if (!candidateService.resolveCompanyIds(scenario).contains(company.getId())) {
                throw new IllegalArgumentException(
                        "Company is not available for investigation in this scenario.");
            }
            if (actionRepository.existsByScenarioIdAndActionTypeAndTargetCompanyId(
                    scenario.getId(), type, company.getId())) {
                throw new IllegalArgumentException(
                        "This company has already been flagged in this scenario.");
            }
            flagCorrect = Boolean.TRUE.equals(company.getShellCompany());
        }
        if (type == InvestigatorActionType.TRACE_TRANSACTION) {
            if (request.getTransactionId() == null) {
                throw new IllegalArgumentException("Transaction is required for tracing.");
            }
            transaction = transactionRepository.findById(request.getTransactionId())
                    .orElseThrow(() -> new IllegalArgumentException(
                            "Transaction is not available for this scenario."));
            if (transaction.getScenario() == null
                    || !scenario.getId().equals(transaction.getScenario().getId())) {
                throw new IllegalArgumentException(
                        "Transaction is not available for this scenario.");
            }
        }

        InvestigatorAction action = new InvestigatorAction();
        action.setScenario(scenario);
        action.setActionType(type);
        action.setTargetCompany(company);
        action.setTransaction(transaction);
        action.setStep(scenario.getStep());
        action.setFlagCorrect(flagCorrect);
        InvestigatorAction saved = actionRepository.save(action);

        CompanyObservationResponse observation = type == InvestigatorActionType.OBSERVE_COMPANY
                ? new CompanyObservationResponse(company) : null;
        DirectorInvestigationResponse directors = type == InvestigatorActionType.INVESTIGATE_DIRECTORS
                ? investigate(company) : null;
        TransactionTraceResponse trace = type == InvestigatorActionType.TRACE_TRANSACTION
                ? new TransactionTraceResponse(transaction) : null;

        int remaining = scenario.getInvestigatorActionsRemaining() - 1;
        scenario.setInvestigatorActionsRemaining(remaining);
        boolean correctlyFlagged = type == InvestigatorActionType.FLAG_COMPANY
                && Boolean.TRUE.equals(flagCorrect);
        if (correctlyFlagged) {
            scenario.setStatus("COMPLETED");
        }
        if (remaining == 0) {
            if (!correctlyFlagged) {
                if (scenario.getStep() >= maxFraudsterTurns) {
                    // Explicit terminal outcome; financial objective remains an independent fact.
                    scenario.setStatus("MAX_TURNS_REACHED");
                } else {
                    scenario.setTurn(FraudTurn.FRAUDSTER);
                }
            }
        }
        scenarioRepository.save(scenario);

        return new InvestigatorActionResponse(saved, observation, directors, trace);
    }

    private boolean requiresCompany(InvestigatorActionType type) {
        return type == InvestigatorActionType.OBSERVE_COMPANY
                || type == InvestigatorActionType.INVESTIGATE_DIRECTORS
                || type == InvestigatorActionType.FLAG_COMPANY;
    }

    private DirectorInvestigationResponse investigate(Company company) {
        List<DirectorRelationshipResponse> directors = companyDirectorRepository
                .findByCompanyId(company.getId())
                .stream()
                .map(CompanyDirector::getDirector)
                .map(director -> new DirectorRelationshipResponse(
                        director.getId(),
                        director.getName(),
                        companyDirectorRepository.findByDirectorId(director.getId())
                                .stream()
                                .map(CompanyDirector::getCompany)
                                .map(CompanyObservationResponse::new)
                                .toList()))
                .toList();
        return new DirectorInvestigationResponse(new CompanyObservationResponse(company), directors);
    }
}
