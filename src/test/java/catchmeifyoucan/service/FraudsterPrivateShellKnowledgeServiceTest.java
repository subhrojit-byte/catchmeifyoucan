package catchmeifyoucan.service;

import catchmeifyoucan.entity.Company;
import catchmeifyoucan.entity.FraudPosition;
import catchmeifyoucan.entity.FraudScenario;
import catchmeifyoucan.entity.FraudTurn;
import catchmeifyoucan.repository.CompanyRepository;
import catchmeifyoucan.repository.FraudScenarioRepository;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.List;
import java.util.Optional;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class FraudsterPrivateShellKnowledgeServiceTest {
    @Test
    void returnsOnlyShellCompaniesAmongTheScenarioLegalIntermediaries() {
        FraudScenarioRepository scenarios = mock(FraudScenarioRepository.class);
        CompanyRepository companies = mock(CompanyRepository.class);
        CompanyRelationshipService relationships = mock(CompanyRelationshipService.class);
        Company source = company(10L, false);
        Company target = company(11L, false);
        FraudScenario scenario = new FraudScenario();
        scenario.setSourceCompany(source);
        scenario.setTargetCompany(target);
        when(scenarios.findById(4L)).thenReturn(Optional.of(scenario));
        when(relationships.eligibleIntermediateCompanyIds(10L, 11L)).thenReturn(Set.of(31L, 30L));
        Company shell31 = company(31L, true);
        Company shell30 = company(30L, true);
        when(companies.findAllById(Set.of(30L, 31L))).thenReturn(List.of(shell31, shell30));

        var service = new FraudsterPrivateShellKnowledgeService(scenarios, companies, relationships);

        assertEquals(List.of(30L, 31L), service.authorizedShellCompanyIds(4L));
        verify(scenarios).findById(4L);
        verify(relationships).eligibleIntermediateCompanyIds(10L, 11L);
    }

    @Test
    void excludesNonShellCandidatesAndFailsClosedForUnknownScenario() {
        FraudScenarioRepository scenarios = mock(FraudScenarioRepository.class);
        CompanyRepository companies = mock(CompanyRepository.class);
        CompanyRelationshipService relationships = mock(CompanyRelationshipService.class);
        FraudScenario scenario = new FraudScenario();
        scenario.setSourceCompany(company(10L, false));
        scenario.setTargetCompany(company(11L, false));
        when(scenarios.findById(4L)).thenReturn(Optional.of(scenario));
        when(scenarios.findById(5L)).thenReturn(Optional.empty());
        when(relationships.eligibleIntermediateCompanyIds(10L, 11L)).thenReturn(Set.of(30L));
        Company nonShell = company(30L, false);
        when(companies.findAllById(Set.of(30L))).thenReturn(List.of(nonShell));

        var service = new FraudsterPrivateShellKnowledgeService(scenarios, companies, relationships);

        assertEquals(List.of(), service.authorizedShellCompanyIds(4L));
        assertThrows(IllegalArgumentException.class, () -> service.authorizedShellCompanyIds(5L));
    }

    @Test
    void legalAuthorizedShellRouteRequiresFundedPositionAndEligibleAuthorizedDestination() {
        FraudScenarioRepository scenarios = mock(FraudScenarioRepository.class);
        CompanyRepository companies = mock(CompanyRepository.class);
        CompanyRelationshipService relationships = mock(CompanyRelationshipService.class);
        FraudScenario scenario = scenario(10L, 11L, 100L);
        when(scenarios.findById(4L)).thenReturn(Optional.of(scenario));
        Company authorizedShell = company(20L, true);
        Company nonShell = company(21L, false);
        when(relationships.eligibleIntermediateCompanyIds(10L, 11L))
                .thenReturn(Set.of(20L, 21L), Set.of(10L, 11L, 20L, 21L));
        when(companies.findAllById(Set.of(20L, 21L)))
                .thenReturn(List.of(authorizedShell, nonShell));
        when(companies.findAllById(Set.of(20L)))
                .thenReturn(List.of(authorizedShell));

        var service = new FraudsterPrivateShellKnowledgeService(scenarios, companies, relationships);

        assertTrue(service.hasLegalAuthorizedShellRoute(4L));
        verify(scenarios, org.mockito.Mockito.times(2)).findById(4L);
        verify(relationships, org.mockito.Mockito.times(2)).eligibleIntermediateCompanyIds(10L, 11L);
        org.mockito.Mockito.verify(scenarios, org.mockito.Mockito.never()).save(scenario);
        org.mockito.Mockito.verify(companies, org.mockito.Mockito.never()).save(
                org.mockito.ArgumentMatchers.any(Company.class));
    }

    @Test
    void validatesAuthorizedShellsAcrossAllPositionsButRoutesOnlyFromFundedPositions() {
        FraudScenarioRepository scenarios = mock(FraudScenarioRepository.class);
        CompanyRepository companies = mock(CompanyRepository.class);
        CompanyRelationshipService relationships = mock(CompanyRelationshipService.class);
        FraudScenario scenario = scenario(10L, 11L, 100L);
        FraudPosition unfundedPosition = new FraudPosition();
        unfundedPosition.setCompany(company(12L, false));
        unfundedPosition.setAmount(java.math.BigDecimal.ZERO);
        ReflectionTestUtils.setField(unfundedPosition, "id", 2L);
        scenario.getPositions().add(unfundedPosition);
        Company authorizedFundedRoute = company(20L, true);
        Company authorizedUnfundedRoute = company(22L, true);

        when(scenarios.findById(4L)).thenReturn(Optional.of(scenario));
        when(relationships.eligibleIntermediateCompanyIds(10L, 11L))
                .thenReturn(Set.of(20L, 22L), Set.of(20L));
        when(relationships.eligibleIntermediateCompanyIds(12L, 11L)).thenReturn(Set.of(22L));
        when(companies.findAllById(Set.of(20L, 22L)))
                .thenReturn(List.of(authorizedFundedRoute, authorizedUnfundedRoute));

        var service = new FraudsterPrivateShellKnowledgeService(scenarios, companies, relationships);

        assertTrue(service.hasLegalAuthorizedShellRoute(4L));
        verify(relationships).eligibleIntermediateCompanyIds(12L, 11L);
        org.mockito.Mockito.verify(scenarios, org.mockito.Mockito.never()).save(scenario);
        org.mockito.Mockito.verify(companies, org.mockito.Mockito.never()).save(
                org.mockito.ArgumentMatchers.any(Company.class));
    }

    @Test
    void routeReadinessExcludesSourceAndTargetFromValidatedCandidates() {
        FraudScenarioRepository scenarios = mock(FraudScenarioRepository.class);
        CompanyRepository companies = mock(CompanyRepository.class);
        CompanyRelationshipService relationships = mock(CompanyRelationshipService.class);
        FraudScenario scenario = scenario(10L, 11L, 100L);
        Company authorizedShell = company(20L, true);
        when(scenarios.findById(4L)).thenReturn(Optional.of(scenario));
        when(relationships.eligibleIntermediateCompanyIds(10L, 11L))
                .thenReturn(Set.of(20L), Set.of(10L, 11L, 20L));
        when(companies.findAllById(Set.of(20L))).thenReturn(List.of(authorizedShell));

        var service = new FraudsterPrivateShellKnowledgeService(scenarios, companies, relationships);

        assertTrue(service.hasLegalAuthorizedShellRoute(4L));
        org.mockito.Mockito.verify(companies, org.mockito.Mockito.times(2)).findAllById(Set.of(20L));
        org.mockito.Mockito.verify(scenarios, org.mockito.Mockito.never()).save(scenario);
        org.mockito.Mockito.verify(companies, org.mockito.Mockito.never()).save(
                org.mockito.ArgumentMatchers.any(Company.class));
    }

    @Test
    void doesNotTreatPositiveBalancePositionWithoutValidIdAsLegalRoute() {
        FraudScenarioRepository scenarios = mock(FraudScenarioRepository.class);
        CompanyRepository companies = mock(CompanyRepository.class);
        CompanyRelationshipService relationships = mock(CompanyRelationshipService.class);
        FraudScenario scenario = scenario(10L, 11L, 100L);
        ReflectionTestUtils.setField(scenario.getPositions().get(0), "id", null);
        Company authorizedShell = company(20L, true);
        when(scenarios.findById(4L)).thenReturn(Optional.of(scenario));
        when(relationships.eligibleIntermediateCompanyIds(10L, 11L)).thenReturn(Set.of(20L));
        when(companies.findAllById(Set.of(20L))).thenReturn(List.of(authorizedShell));

        var service = new FraudsterPrivateShellKnowledgeService(scenarios, companies, relationships);

        assertFalse(service.hasLegalAuthorizedShellRoute(4L));
        org.mockito.Mockito.verify(scenarios, org.mockito.Mockito.never()).save(scenario);
        org.mockito.Mockito.verify(companies, org.mockito.Mockito.never()).save(
                org.mockito.ArgumentMatchers.any(Company.class));
    }

    @Test
    void routeReadinessIsFalseWhenTheEligibleIntermediariesContainNoAuthorizedShell() {
        FraudScenarioRepository scenarios = mock(FraudScenarioRepository.class);
        CompanyRepository companies = mock(CompanyRepository.class);
        CompanyRelationshipService relationships = mock(CompanyRelationshipService.class);
        FraudScenario scenario = scenario(10L, 11L, 100L);
        Company nonShell = company(20L, false);
        when(scenarios.findById(4L)).thenReturn(Optional.of(scenario));
        when(relationships.eligibleIntermediateCompanyIds(10L, 11L)).thenReturn(Set.of(20L));
        when(companies.findAllById(Set.of(20L))).thenReturn(List.of(nonShell));

        var service = new FraudsterPrivateShellKnowledgeService(scenarios, companies, relationships);

        assertFalse(service.hasLegalAuthorizedShellRoute(4L));
        org.mockito.Mockito.verify(relationships).eligibleIntermediateCompanyIds(10L, 11L);
        org.mockito.Mockito.verify(scenarios, org.mockito.Mockito.never()).save(scenario);
        org.mockito.Mockito.verify(companies, org.mockito.Mockito.never()).save(
                org.mockito.ArgumentMatchers.any(Company.class));
    }

    private static FraudScenario scenario(long sourceId, long targetId, long amount) {
        FraudScenario scenario = new FraudScenario();
        Company source = company(sourceId, false);
        scenario.setSourceCompany(source);
        scenario.setTargetCompany(company(targetId, false));
        scenario.setStatus("ACTIVE");
        scenario.setTurn(FraudTurn.FRAUDSTER);
        FraudPosition position = new FraudPosition();
        position.setCompany(source);
        position.setAmount(java.math.BigDecimal.valueOf(amount));
        ReflectionTestUtils.setField(position, "id", 1L);
        scenario.getPositions().add(position);
        return scenario;
    }

    private static Company company(long id, boolean shell) {
        Company company = mock(Company.class);
        when(company.getId()).thenReturn(id);
        when(company.getShellCompany()).thenReturn(shell);
        return company;
    }
}
