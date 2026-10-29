package catchmeifyoucan.service;

import catchmeifyoucan.entity.Company;
import catchmeifyoucan.entity.CompanyDirector;
import catchmeifyoucan.entity.Director;
import catchmeifyoucan.repository.CompanyDirectorRepository;
import catchmeifyoucan.repository.CompanyRepository;
import catchmeifyoucan.repository.DirectorRepository;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
public class CompanyDirectorService {

    private final CompanyDirectorRepository companyDirectorRepository;
    private final CompanyRepository companyRepository;
    private final DirectorRepository directorRepository;

    public CompanyDirectorService(
            CompanyDirectorRepository companyDirectorRepository,
            CompanyRepository companyRepository,
            DirectorRepository directorRepository) {

        this.companyDirectorRepository = companyDirectorRepository;
        this.companyRepository = companyRepository;
        this.directorRepository = directorRepository;
    }

    public CompanyDirector assignDirector(
            Long companyId,
            Long directorId) {

        Company company = companyRepository.findById(companyId)
                .orElseThrow(() ->
                        new RuntimeException("Company not found"));

        Director director = directorRepository.findById(directorId)
                .orElseThrow(() ->
                        new RuntimeException("Director not found"));

        CompanyDirector companyDirector =
                new CompanyDirector(company, director);

        return companyDirectorRepository.save(companyDirector);
    }

    public List<CompanyDirector> getDirectorsForCompany(Long companyId) {
        return companyDirectorRepository.findByCompanyId(companyId);
    }

    public List<CompanyDirector> getCompaniesForDirector(Long directorId) {
        return companyDirectorRepository.findByDirectorId(directorId);
    }
}