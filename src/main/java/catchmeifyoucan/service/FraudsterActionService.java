package catchmeifyoucan.service;

import catchmeifyoucan.dto.FraudsterActionRequest;
import catchmeifyoucan.dto.FraudsterActionTargetRequest;
import catchmeifyoucan.entity.Company;
import catchmeifyoucan.entity.FraudAction;
import catchmeifyoucan.entity.FraudActionTarget;
import catchmeifyoucan.entity.FraudActionType;
import catchmeifyoucan.entity.FraudPosition;
import catchmeifyoucan.entity.FraudScenario;
import catchmeifyoucan.entity.FraudTurn;
import catchmeifyoucan.entity.Transaction;
import catchmeifyoucan.entity.TransactionOrigin;
import catchmeifyoucan.repository.CompanyRepository;
import catchmeifyoucan.repository.FraudActionRepository;
import catchmeifyoucan.repository.FraudScenarioRepository;
import catchmeifyoucan.repository.TransactionRepository;
import catchmeifyoucan.simulation.TransactionChannelGenerator;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.Random;

@Service
public class FraudsterActionService {

    private final FraudScenarioRepository fraudScenarioRepository;
    private final FraudActionRepository fraudActionRepository;
    private final CompanyRepository companyRepository;
    private final TransactionRepository transactionRepository;
    private final CompanyRelationshipService companyRelationshipService;
    private final BackgroundTransactionService backgroundTransactionService;

    public FraudsterActionService(
            FraudScenarioRepository fraudScenarioRepository,
            FraudActionRepository fraudActionRepository,
            CompanyRepository companyRepository,
            TransactionRepository transactionRepository,
            CompanyRelationshipService companyRelationshipService,
            BackgroundTransactionService backgroundTransactionService) {

        this.fraudScenarioRepository = fraudScenarioRepository;
        this.fraudActionRepository = fraudActionRepository;
        this.companyRepository = companyRepository;
        this.transactionRepository = transactionRepository;
        this.companyRelationshipService = companyRelationshipService;
        this.backgroundTransactionService = backgroundTransactionService;
    }

    @Transactional
    public FraudAction createAction(FraudsterActionRequest request) {
        if (request == null || request.getScenarioId() == null) {
            throw new IllegalArgumentException("Scenario is required.");
        }

        FraudScenario scenario = fraudScenarioRepository
                .findById(request.getScenarioId())
                .orElseThrow(() -> new IllegalArgumentException("Scenario not found."));

        if (scenario.getTurn() != FraudTurn.FRAUDSTER) {
            throw new IllegalArgumentException("It is not the fraudster turn.");
        }

        if (request.getSourcePositionId() == null) {
            throw new IllegalArgumentException("Source position is required.");
        }

        FraudPosition sourcePosition = scenario.getPositions().stream()
                .filter(position -> request.getSourcePositionId().equals(position.getId()))
                .findFirst()
                .orElseThrow(() -> new IllegalArgumentException(
                        "Source position not found for scenario."));

        if (request.getActionType() == null) {
            throw new IllegalArgumentException("Action type is required.");
        }

        List<FraudsterActionTargetRequest> targets = request.getTargets() == null
                ? Collections.emptyList()
                : request.getTargets();

        if (!(request.getActionType() == FraudActionType.DIRECT_TRANSFER
                && targets.size() <= 1)) {
            validateTargetCount(request.getActionType(), targets);
        }
        if (request.getActionType() == FraudActionType.DIRECT_TRANSFER) {
            if (sourcePosition.getAmount() == null
                    || sourcePosition.getAmount().compareTo(BigDecimal.ZERO) <= 0) {
                throw new IllegalArgumentException("Insufficient funds in source position.");
            }
        } else {
            validateTargets(request.getActionType(), targets, sourcePosition, scenario);
        }

        FraudAction action = new FraudAction();
        action.setScenario(scenario);
        action.setActionType(request.getActionType());
        action.setSourcePosition(sourcePosition);
        action.setStep(scenario.getStep());

        List<FraudsterActionTargetRequest> normalizedTargets = targets;
        if (request.getActionType() == FraudActionType.DIRECT_TRANSFER) {
            FraudsterActionTargetRequest targetRequest = new FraudsterActionTargetRequest();
            targetRequest.setDestinationCompanyId(scenario.getTargetCompany().getId());
            targetRequest.setAmount(sourcePosition.getAmount());
            normalizedTargets = List.of(targetRequest);
        }

        for (FraudsterActionTargetRequest targetRequest : normalizedTargets) {
            Company destinationCompany = companyRepository
                    .findById(targetRequest.getDestinationCompanyId())
                    .orElseThrow(() -> new IllegalArgumentException(
                            "Destination company not found."));

            FraudActionTarget target = new FraudActionTarget();
            target.setAction(action);
            target.setDestinationCompany(destinationCompany);
            target.setAmount(request.getActionType() == FraudActionType.ROUTE_TRANSFER
                    ? sourcePosition.getAmount()
                    : targetRequest.getAmount());
            action.getTargets().add(target);
        }

        return fraudActionRepository.save(action);
    }

    @Transactional
    public FraudScenario executeAction(Long actionId) {
        if (actionId == null) {
            throw new IllegalArgumentException("Action is required.");
        }

        FraudAction action = fraudActionRepository
                .findById(actionId)
                .orElseThrow(() -> new IllegalArgumentException("Action not found."));

        if (action.getScenario() == null || action.getScenario().getId() == null) {
            throw new IllegalArgumentException("Scenario not found.");
        }

        FraudScenario scenario = fraudScenarioRepository
                .findById(action.getScenario().getId())
                .orElseThrow(() -> new IllegalArgumentException("Scenario not found."));

        if (!"ACTIVE".equals(scenario.getStatus())) {
            throw new IllegalArgumentException("Scenario is not ACTIVE.");
        }

        if (scenario.getTurn() != FraudTurn.FRAUDSTER) {
            throw new IllegalArgumentException("It is not the fraudster turn.");
        }

        if (action.getStep() != scenario.getStep()) {
            throw new IllegalArgumentException("Action step is stale.");
        }

        if (action.getSourcePosition() == null
                || action.getSourcePosition().getId() == null) {
            throw new IllegalArgumentException("Source position not found.");
        }

        FraudPosition sourcePosition = scenario.getPositions().stream()
                .filter(position -> action.getSourcePosition().getId()
                        .equals(position.getId()))
                .findFirst()
                .orElseThrow(() -> new IllegalArgumentException(
                        "Source position does not belong to scenario."));

        if (action.getActionType() == null) {
            throw new IllegalArgumentException("Action type is required.");
        }

        List<FraudActionTarget> targets = action.getTargets() == null
                ? Collections.emptyList()
                : action.getTargets();

        validateExecutionTargets(action.getActionType(), targets, sourcePosition, scenario);

        if (action.getActionType() != FraudActionType.WAIT) {
            List<Transaction> transactions = new ArrayList<>();
            Random transactionRandom = new Random(
                    (scenario.getId() == null ? 0L : scenario.getId()) * 31L
                            + action.getStep());

            for (FraudActionTarget target : targets) {
                if (action.getActionType() == FraudActionType.DIRECT_TRANSFER
                        || action.getActionType() == FraudActionType.ROUTE_TRANSFER) {
                    target.setAmount(sourcePosition.getAmount());
                }
                transferMoney(
                        scenario,
                        action,
                        sourcePosition,
                        target,
                        transactions,
                        transactionRandom
                );
            }

            transactionRepository.saveAll(transactions);
            updateFinancialObjectiveStatus(scenario);
        }

        // This is inside the same transaction as the successful action. The
        // persisted marker prevents a retry from creating another background tick.
        backgroundTransactionService.generateForSuccessfulAction(scenario, action);

        scenario.setStep(scenario.getStep() + 1);
        scenario.setTurn(FraudTurn.INVESTIGATOR);
        scenario.setInvestigatorActionsRemaining(3);

        return fraudScenarioRepository.save(scenario);
    }

    private void validateExecutionTargets(
            FraudActionType actionType,
            List<FraudActionTarget> targets,
            FraudPosition sourcePosition,
            FraudScenario scenario) {

        validateTargetCount(actionType, targets.size());

        if (sourcePosition.getAmount() == null
                || sourcePosition.getAmount().compareTo(BigDecimal.ZERO) < 0) {
            throw new IllegalArgumentException("Source position has invalid amount.");
        }

        if (actionType == FraudActionType.WAIT) {
            return;
        }

        if ((actionType == FraudActionType.DIRECT_TRANSFER
                || actionType == FraudActionType.ROUTE_TRANSFER)
                && sourcePosition.getAmount().compareTo(BigDecimal.ZERO) <= 0) {
            throw new IllegalArgumentException("Insufficient funds in source position.");
        }

        Set<Long> destinationCompanyIds = new HashSet<>();
        Set<Long> eligibleIntermediateIds = actionType == FraudActionType.ROUTE_TRANSFER
                || actionType == FraudActionType.SPLIT_TRANSFER
                ? companyRelationshipService.eligibleIntermediateCompanyIds(
                        sourcePosition.getCompany().getId(), scenario.getTargetCompany().getId())
                : Collections.emptySet();
        if ((actionType == FraudActionType.ROUTE_TRANSFER
                || actionType == FraudActionType.SPLIT_TRANSFER) && eligibleIntermediateIds.isEmpty()) {
            throw new IllegalArgumentException(
                    "No eligible intermediate destination shares a director with the source company.");
        }
        BigDecimal totalAmount = BigDecimal.ZERO;

        for (FraudActionTarget target : targets) {
            if (target == null || target.getDestinationCompany() == null
                    || target.getDestinationCompany().getId() == null) {
                throw new IllegalArgumentException("Destination company is required.");
            }

            Company destinationCompany = companyRepository
                    .findById(target.getDestinationCompany().getId())
                    .orElseThrow(() -> new IllegalArgumentException(
                            "Destination company not found."));

            if (destinationCompany.getId().equals(sourcePosition.getCompany().getId())) {
                throw new IllegalArgumentException(
                        "Destination company must differ from source position company.");
            }

            if (actionType == FraudActionType.DIRECT_TRANSFER
                    && !destinationCompany.getId().equals(scenario.getTargetCompany().getId())) {
                throw new IllegalArgumentException(
                        "Direct transfer destination must be the scenario target company.");
            }

            if (actionType == FraudActionType.ROUTE_TRANSFER
                    && destinationCompany.getId().equals(scenario.getTargetCompany().getId())) {
                throw new IllegalArgumentException(
                        "Route transfer destination must be an intermediate company.");
            }

            if ((actionType == FraudActionType.ROUTE_TRANSFER
                    || actionType == FraudActionType.SPLIT_TRANSFER)
                    && !eligibleIntermediateIds.contains(destinationCompany.getId())) {
                throw new IllegalArgumentException(
                        "Destination company must share a director with the source company and be an intermediate company.");
            }

            if (actionType == FraudActionType.SPLIT_TRANSFER
                    && (target.getAmount() == null
                    || target.getAmount().compareTo(BigDecimal.ZERO) <= 0)) {
                throw new IllegalArgumentException(
                        "Target amount must be greater than zero.");
            }

            if (actionType == FraudActionType.SPLIT_TRANSFER
                    && !destinationCompanyIds.add(destinationCompany.getId())) {
                throw new IllegalArgumentException(
                        "Split transfer destination companies must not be duplicated.");
            }

            if (target.getAmount() != null) {
                totalAmount = totalAmount.add(target.getAmount());
            }
        }

        if (actionType == FraudActionType.SPLIT_TRANSFER
                && totalAmount.compareTo(sourcePosition.getAmount()) != 0) {
            throw new IllegalArgumentException(
                    "Split transfer target amounts must equal source position amount.");
        }

        if (actionType != FraudActionType.SPLIT_TRANSFER
                && actionType != FraudActionType.DIRECT_TRANSFER
                && actionType != FraudActionType.ROUTE_TRANSFER
                && totalAmount.compareTo(sourcePosition.getAmount()) > 0) {
            throw new IllegalArgumentException("Insufficient funds in source position.");
        }
    }

    private void transferMoney(
            FraudScenario scenario,
            FraudAction action,
            FraudPosition sourcePosition,
            FraudActionTarget target,
            List<Transaction> transactions,
            Random transactionRandom) {

        BigDecimal amount = target.getAmount();

        sourcePosition.setAmount(sourcePosition.getAmount().subtract(amount));

        FraudPosition destinationPosition = scenario.getPositions().stream()
                .filter(position -> position.getCompany().getId()
                        .equals(target.getDestinationCompany().getId()))
                .findFirst()
                .orElseGet(() -> {
                    FraudPosition newPosition = new FraudPosition();
                    newPosition.setScenario(scenario);
                    newPosition.setCompany(target.getDestinationCompany());
                    newPosition.setAmount(BigDecimal.ZERO);
                    scenario.getPositions().add(newPosition);
                    return newPosition;
                });

        destinationPosition.setAmount(destinationPosition.getAmount().add(amount));

        Transaction transaction = new Transaction();
        transaction.setSourceCompany(sourcePosition.getCompany());
        transaction.setDestinationCompany(target.getDestinationCompany());
        transaction.setAmount(amount);
        transaction.setChannel(TransactionChannelGenerator.generateChannel(transactionRandom));
        transaction.setTimestamp(LocalDateTime.now());
        transaction.setOrigin(TransactionOrigin.FRAUDSTER_ACTION);
        transaction.setScenario(scenario);
        transaction.setFraudAction(action);
        transactions.add(transaction);
    }

    private void updateFinancialObjectiveStatus(FraudScenario scenario) {
        BigDecimal targetCompanyAmount = scenario.getPositions().stream()
                .filter(position -> position.getCompany().getId()
                        .equals(scenario.getTargetCompany().getId()))
                .map(FraudPosition::getAmount)
                .reduce(BigDecimal.ZERO, BigDecimal::add);

        if (targetCompanyAmount.compareTo(scenario.getTargetAmount()) >= 0) {
            scenario.setFinancialObjectiveAchieved(true);
        }
    }

    private void validateTargetCount(
            FraudActionType actionType,
            List<FraudsterActionTargetRequest> targets) {

        validateTargetCount(actionType, targets.size());
    }

    private void validateTargetCount(
            FraudActionType actionType,
            int targetCount) {

        switch (actionType) {
            case DIRECT_TRANSFER, ROUTE_TRANSFER -> {
                if (targetCount != 1) {
                    throw new IllegalArgumentException(
                            "Direct and route transfers require exactly one target.");
                }
            }
            case SPLIT_TRANSFER -> {
                if (targetCount < 2) {
                    throw new IllegalArgumentException(
                            "Split transfers require at least two targets.");
                }
            }
            case WAIT -> {
                if (targetCount != 0) {
                    throw new IllegalArgumentException(
                            "Wait actions must not contain targets.");
                }
            }
        }
    }

    private void validateTargets(
            FraudActionType actionType,
            List<FraudsterActionTargetRequest> targets,
            FraudPosition sourcePosition,
            FraudScenario scenario) {

        if (sourcePosition.getAmount() == null
                || sourcePosition.getAmount().compareTo(BigDecimal.ZERO) < 0) {
            throw new IllegalArgumentException("Source position has invalid amount.");
        }

        if (actionType == FraudActionType.WAIT) {
            return;
        }

        Set<Long> destinationCompanyIds = new HashSet<>();
        Set<Long> eligibleIntermediateIds = actionType == FraudActionType.ROUTE_TRANSFER
                || actionType == FraudActionType.SPLIT_TRANSFER
                ? companyRelationshipService.eligibleIntermediateCompanyIds(
                        sourcePosition.getCompany().getId(), scenario.getTargetCompany().getId())
                : Collections.emptySet();
        if ((actionType == FraudActionType.ROUTE_TRANSFER
                || actionType == FraudActionType.SPLIT_TRANSFER) && eligibleIntermediateIds.isEmpty()) {
            throw new IllegalArgumentException(
                    "No eligible intermediate destination shares a director with the source company.");
        }
        BigDecimal totalAmount = BigDecimal.ZERO;

        for (FraudsterActionTargetRequest target : targets) {
            if (target == null || target.getDestinationCompanyId() == null) {
                throw new IllegalArgumentException("Destination company is required.");
            }

            if (actionType == FraudActionType.SPLIT_TRANSFER
                    && (target.getAmount() == null
                    || target.getAmount().compareTo(BigDecimal.ZERO) <= 0)) {
                throw new IllegalArgumentException(
                        "Target amount must be greater than zero.");
            }

            Company destinationCompany = companyRepository
                    .findById(target.getDestinationCompanyId())
                    .orElseThrow(() -> new IllegalArgumentException(
                            "Destination company not found."));

            if (destinationCompany.getId().equals(sourcePosition.getCompany().getId())) {
                throw new IllegalArgumentException(
                        "Destination company must differ from source position company.");
            }

            if (actionType == FraudActionType.DIRECT_TRANSFER
                    && !destinationCompany.getId().equals(scenario.getTargetCompany().getId())) {
                throw new IllegalArgumentException(
                        "Direct transfer destination must be the scenario target company.");
            }

            if (actionType == FraudActionType.ROUTE_TRANSFER
                    && destinationCompany.getId().equals(scenario.getTargetCompany().getId())) {
                throw new IllegalArgumentException(
                        "Route transfer destination must be an intermediate company.");
            }

            if ((actionType == FraudActionType.ROUTE_TRANSFER
                    || actionType == FraudActionType.SPLIT_TRANSFER)
                    && !eligibleIntermediateIds.contains(destinationCompany.getId())) {
                throw new IllegalArgumentException(
                        "Destination company must share a director with the source company and be an intermediate company.");
            }

            if (actionType == FraudActionType.SPLIT_TRANSFER
                    && !destinationCompanyIds.add(destinationCompany.getId())) {
                throw new IllegalArgumentException(
                        "Split transfer destination companies must not be duplicated.");
            }

            if (target.getAmount() != null) {
                totalAmount = totalAmount.add(target.getAmount());
            }
        }

        if ((actionType == FraudActionType.DIRECT_TRANSFER
                || actionType == FraudActionType.ROUTE_TRANSFER)
                && sourcePosition.getAmount().compareTo(BigDecimal.ZERO) <= 0) {
            throw new IllegalArgumentException("Insufficient funds in source position.");
        }

        if (actionType == FraudActionType.SPLIT_TRANSFER
                && totalAmount.compareTo(sourcePosition.getAmount()) != 0) {
            throw new IllegalArgumentException(
                    "Split transfer target amounts must equal source position amount.");
        }
    }
}
