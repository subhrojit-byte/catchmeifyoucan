package catchmeifyoucan.service;

import catchmeifyoucan.entity.Company;
import catchmeifyoucan.entity.CompanyDirector;
import catchmeifyoucan.entity.Director;
import catchmeifyoucan.repository.CompanyDirectorRepository;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.List;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class CompanyRelationshipServiceTest {

    @Mock private CompanyDirectorRepository repository;

    @Test
    void sharedDirectorsProduceEligibleIntermediateCompaniesAndExcludeSourceTarget() {
        Company source = company(1L);
        Company target = company(2L);
        Company eligible = company(3L);
        Company other = company(4L);
        Director first = director(10L);
        Director second = director(11L);

        when(repository.findByCompanyId(1L)).thenReturn(List.of(
                new CompanyDirector(source, first), new CompanyDirector(source, second)));
        when(repository.findByDirectorId(10L)).thenReturn(List.of(
                new CompanyDirector(source, first), new CompanyDirector(eligible, first)));
        when(repository.findByDirectorId(11L)).thenReturn(List.of(
                new CompanyDirector(target, second), new CompanyDirector(other, second)));

        Set<Long> result = new CompanyRelationshipService(repository)
                .eligibleIntermediateCompanyIds(1L, 2L);

        assertEquals(Set.of(3L, 4L), result);
    }

    private Company company(Long id) {
        Company company = new Company();
        ReflectionTestUtils.setField(company, "id", id);
        return company;
    }

    private Director director(Long id) {
        Director director = new Director();
        ReflectionTestUtils.setField(director, "id", id);
        return director;
    }
}
