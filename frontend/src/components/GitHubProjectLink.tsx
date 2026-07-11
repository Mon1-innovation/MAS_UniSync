import {MarkGithubIcon} from '@primer/octicons-react'

export const githubRepositoryUrl = 'https://github.com/Mon1-innovation/MAS_UniSync'

type GitHubProjectLinkProps = {
  className?: string
}

export function GitHubProjectLink({className}: GitHubProjectLinkProps) {
  return (
    <a
      className={className ? `github-project-link ${className}` : 'github-project-link'}
      href={githubRepositoryUrl}
      target="_blank"
      rel="noreferrer"
      aria-label="GitHub repository"
      title="GitHub repository"
    >
      <MarkGithubIcon size={18} aria-hidden="true" />
    </a>
  )
}
