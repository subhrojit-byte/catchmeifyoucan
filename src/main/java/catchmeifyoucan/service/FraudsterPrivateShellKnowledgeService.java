package catchmeifyoucan.service;

import catchmeifyoucan.entity.Company;
import catchmeifyoucan.entity.FraudScenario;
import catchmeifyoucan.entity.FraudPosition;
import catchmeifyoucan.entity.FraudTurn;
import catchmeifyoucan.repository.CompanyRepository;
import catchmeifyoucan.repository.FraudScenarioRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;

/**
 * Resolves the shell companies explicitly authorized for a fraudster run.
 * Authorization is scenario-specific and limited to legal intermediary
 * companies; it does not assert that the fraudster owns or controls them.
 */
@Service
public class FraudsterPrivateShellKnowledgeService {
    private final FraudScenarioRepository scenarioRepository;
    private final CompanyRepository companyRepository;
    private final CompanyRelationshipService relationshipService;

    public FraudsterPrivateShellKnowledgeService(
            FraudScenarioRepository scenarioRepository,
            CompanyRepository companyRepository,
            CompanyRelationshipService relationshipService) {
        this.scenarioRepository = scenarioRepository;
        this.companyRepository = companyRepository;
        this.relationshipService = relationshipService;
    }

    @Transactional(readOnly = true)
    public List<Long> authorizedShellCompanyIds(long scenarioId) {
        if (scenarioId <= 0) {
            throw new IllegalArgumentException("A valid scenario is required.");
        }
        FraudScenario scenario = scenarioRepository.findById(scenarioId)
                .orElseThrow(() -> new IllegalArgumentException("Scenario is unavailable."));
        Company source = scenario.getSourceCompany();
        Company target = scenario.getTargetCompany();
        if (source == null || source.getId() == null || target == null || target.getId() == null) {
            throw new IllegalStateException("Scenario company scope is invalid.");
        }

        Set<Long> eligibleIds = relationshipService.eligibleIntermediateCompanyIds(
                source.getId(), target.getId());
        if (eligibleIds == null) {
            throw new IllegalStateException("Scenario intermediary eligibility is unavailable.");
        }
        Set<Long> validEligibleIds = new TreeSet<>();
        for (Long id : eligibleIds) {
            if (id == null || id <= 0 || id.equals(source.getId()) || id.equals(target.getId())) {
                throw new IllegalStateException("Scenario intermediary eligibility is invalid.");
            }
            validEligibleIds.add(id);
        }
        if (validEligibleIds.isEmpty()) {
            return List.of();
        }

        List<Company> companies = companyRepository.findAllById(validEligibleIds);
        Set<Long> foundIds = new TreeSet<>();
        List<Long> shells = new ArrayList<>();
        for (Company company : companies) {
            if (company == null || company.getId() == null || !validEligibleIds.contains(company.getId())) {
                throw new IllegalStateException("Scenario intermediary records are invalid.");
            }
            foundIds.add(company.getId());
            if (Boolean.TRUE.equals(company.getShellCompany())) {
                shells.add(company.getId());
            }
        }
        if (!foundIds.equals(validEligibleIds)) {
            throw new IllegalStateException("Scenario intermediary records are incomplete.");
        }
        shells.sort(Long::compareTo);
        return List.copyOf(shells);
    }

    /** Return only readiness; authorized shell IDs remain inside this service. */
    @Transactional(readOnly = true)
    public boolean hasLegalAuthorizedShellRoute(long scenarioId) {
        if (scenarioId <= 0) {
            throw new IllegalArgumentException("A valid scenario is required.");
        }
        FraudScenario scenario = scenarioRepository.findById(scenarioId)
                .orElseThrow(() -> new IllegalArgumentException("Scenario is unavailable."));
        if (!"ACTIVE".equals(scenario.getStatus()) || scenario.getTurn() != FraudTurn.FRAUDSTER) {
            return false;
        }
        if (scenario.getTargetCompany() == null || scenario.getTargetCompany().getId() == null) {
            throw new IllegalStateException("Scenario company scope is invalid.");
        }

        Set<Long> authorizedShells = Set.copyOf(authorizedShellCompanyIds(scenarioId));
        if (authorizedShells.isEmpty()) {
            return false;
        }
        Long targetId = scenario.getTargetCompany().getId();
        Set<Long> eligibleAcrossPositions = new HashSet<>();
        Set<Long> legalRouteDestinations = new HashSet<>();
        Map<Long, Set<Long>> eligibleByPositionSource = new HashMap<>();
        for (FraudPosition position : scenario.getPositions()) {
            if (position == null || position.getCompany() == null
                    || position.getCompany().getId() == null || position.getCompany().getId() <= 0) {
                continue;
            }
            Long positionCompanyId = position.getCompany().getId();
            eligibleByPositionSource.computeIfAbsent(positionCompanyId, sourceId -> {
                Set<Long> legalDestinations = relationshipService.eligibleIntermediateCompanyIds(
                        sourceId, targetId);
                if (legalDestinations == null) {
                    throw new IllegalStateException("Scenario intermediary eligibility is unavailable.");
                }
                Set<Long> validDestinations = new HashSet<>();
                for (Long destinationId : legalDestinations) {
                    if (destinationId == null || destinationId <= 0) {
                        throw new IllegalStateException("Scenario intermediary eligibility is invalid.");
                    }
                    if (!destinationId.equals(sourceId) && !destinationId.equals(targetId)) {
                        validDestinations.add(destinationId);
                    }
                }
                eligibleAcrossPositions.addAll(validDestinations);
                return validDestinations;
            });

            // Match legal_fraudster_actions(): only persisted positions with valid IDs,
            // valid source IDs, positive balances, and a non-target source can route.
            if (position.getId() != null && position.getId() > 0
                    && position.getAmount() != null && position.getAmount().signum() > 0
                    && !positionCompanyId.equals(targetId)) {
                legalRouteDestinations.addAll(eligibleByPositionSource.get(positionCompanyId));
            }
        }
        if (!eligibleAcrossPositions.containsAll(authorizedShells)) {
            return false;
        }
        Set<Long> validatedCompanyIds = new HashSet<>();
        for (Company company : companyRepository.findAllById(eligibleAcrossPositions)) {
            if (company != null && company.getId() != null) {
                validatedCompanyIds.add(company.getId());
            }
        }
        if (!validatedCompanyIds.equals(eligibleAcrossPositions)) {
            throw new IllegalStateException("Scenario intermediary records are incomplete.");
        }
        return legalRouteDestinations.stream().anyMatch(authorizedShells::contains);
    }
}
