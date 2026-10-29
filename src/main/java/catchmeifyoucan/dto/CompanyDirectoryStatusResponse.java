package catchmeifyoucan.dto;

import catchmeifyoucan.entity.Company;

/** Ground-truth status for the localhost-only human Company Directory. */
public record CompanyDirectoryStatusResponse(Long id, Boolean shellCompany) {
    public CompanyDirectoryStatusResponse(Company company) {
        this(company.getId(), company.getShellCompany());
    }
}
